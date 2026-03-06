"""
revanced_only.py — Auto-setup + ReVanced patcher for Facebook Messenger.

1. Validates environment (Java version, disk space, platform)
2. Auto-detects and renames APKMirror APK filename
3. Checks dependencies, auto-updates CLI/patches, downloads missing tools
4. Interactive patch selection (skip with -y flag)
5. Runs ReVanced patch with DUMMYVAL/.2 directory watcher
6. Outputs final-messenger-apk.apk for MT Manager manifest fix + signing

Usage:
  python revanced_only.py        # interactive patch selection
  python revanced_only.py -y     # use default patches, no prompts
"""

import subprocess, urllib.request, urllib.error
from datetime import datetime
import os, sys, threading, time, glob, shutil
import zipfile, json, hashlib, platform, ssl, re, argparse

# ─── ARGS ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="ReVanced patcher for Facebook Messenger")
parser.add_argument("-y", "--yes", action="store_true", help="Use default patches without prompting")
args = parser.parse_args()

# ─── CONFIG ───────────────────────────────────────────────────────────────────
APK_IN      = None  # Auto-detected at runtime
# PATCHED_APK is set dynamically at runtime with timestamp
TEMP_DIR    = "messenger_revanced-temporary-files"
DEST        = os.getcwd()
JAVA_MIN    = 11
SYSTEM      = platform.system()
AAPT2_BIN   = "aapt2.exe" if SYSTEM == "Windows" else "aapt2"

PATCHES = [
    "Hide inbox ads",
    "Hide inbox subtabs",
    "Remove Meta AI",
    "Hide Facebook button",
    "Disable Pairip license check",
    "Disable Play Integrity",
    "Prevent screenshot detection",
]

AAPT2_URLS = {
    "Windows": "https://dl.google.com/android/maven2/com/android/tools/build/aapt2/9.2.0-alpha02-14792394/aapt2-9.2.0-alpha02-14792394-windows.jar",
    "Linux":   "https://dl.google.com/android/maven2/com/android/tools/build/aapt2/9.2.0-alpha02-14792394/aapt2-9.2.0-alpha02-14792394-linux.jar",
    "Darwin":  "https://dl.google.com/android/maven2/com/android/tools/build/aapt2/9.2.0-alpha02-14792394/aapt2-9.2.0-alpha02-14792394-osx.jar",
}
AAPT2_JAR_NAME = {
    "Windows": "aapt2-windows.jar",
    "Linux":   "aapt2-linux.jar",
    "Darwin":  "aapt2-osx.jar",
}

# ─── HTTPS + SSL ──────────────────────────────────────────────────────────────
SSL_CTX = ssl.create_default_context()

def open_url(url, timeout=30, resume_from=0):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "revanced-patcher/1.0")
    if resume_from > 0:
        req.add_header("Range", f"bytes={resume_from}-")
    return urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout)

# ─── RETRY ────────────────────────────────────────────────────────────────────
RETRYABLE = (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError)

def with_retry(fn, retries=4, backoff=2):
    for attempt in range(retries):
        try:
            return fn()
        except RETRYABLE as e:
            if attempt == retries - 1:
                raise
            wait = backoff ** attempt
            print(f"  [RETRY]: {e} — retrying in {wait}s ({attempt+1}/{retries-1})")
            time.sleep(wait)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def human_size(b):
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def fetch_sha256(url):
    for ext in [".sha256", ".sha256sum", ".sha256.txt"]:
        try:
            with open_url(url + ext, timeout=10) as r:
                return r.read().decode().strip().split()[0]
        except Exception:
            continue
    return None

def verify_apk(path):
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic != b"PK\x03\x04":
        print(f"[ERROR]: {path} is not a valid APK.")
        sys.exit(1)
    print("[ENV]: APK magic bytes OK ✓")

def check_disk_space(apk_path):
    apk_size = os.path.getsize(apk_path) if os.path.exists(apk_path) else 0
    required_mb = max(500, int(apk_size * 3 / (1024 * 1024)) + 200)
    free_mb = shutil.disk_usage(DEST).free / (1024 * 1024)
    if free_mb < required_mb:
        print(f"[ERROR]: Need ~{required_mb}MB free, have {free_mb:.0f}MB.")
        sys.exit(1)
    print(f"[ENV]: Disk space OK ({free_mb:.0f}MB free, need ~{required_mb}MB)")

def check_java():
    try:
        result = subprocess.run(["java", "-version"], capture_output=True, text=True)
        output = result.stderr or result.stdout
        match = re.search(r'version\s+"(\d+)(?:\.(\d+))?', output, re.IGNORECASE)
        if match:
            major = int(match.group(1))
            if major == 1:
                minor = match.group(2)
                major = int(minor) if minor is not None else 8
            if major < JAVA_MIN:
                print(f"[ERROR]: Java {major} found. Need Java {JAVA_MIN}+. https://adoptium.net")
                sys.exit(1)
            print(f"[ENV]: Java {major} detected — OK")
        else:
            print(f"[WARN]: Could not parse Java version: {output.strip()[:80]}")
    except FileNotFoundError:
        print("[ERROR]: Java not found. Install from https://adoptium.net")
        sys.exit(1)

# ─── APK AUTO-DETECT & RENAME ─────────────────────────────────────────────────
def parse_version(ver_str):
    """Convert version string to tuple for comparison."""
    try:
        return tuple(int(x) for x in ver_str.split("."))
    except Exception:
        return (0,)

def find_and_rename_apkmirror_apk():
    """Detect all Messenger APKs, pick highest version, rename if needed."""
    short_pat = re.compile(r'^com\.facebook\.orca_(\d+\.\d+\.\d+\.\d+)\.com\.apk$', re.I)
    apkm_pats = [
        re.compile(r'^(com\.facebook\.orca)_(\d+\.\d+\.\d+\.\d+)-\d+_.*_apkmirror\.com\.apk$', re.I),
        re.compile(r'^(com\.facebook\.orca)_(\d+\.\d+\.\d+\.\d+).*_apkmirror\.com\.apk$', re.I),
    ]

    print("[APK]: Scanning for APK files...")
    apks = [f for f in os.listdir(DEST) if f.endswith(".apk")]
    if not apks:
        print("  [APK]: No .apk files found")
        return None
    for f in apks:
        print(f"    - {f}")

    # Collect all candidates: (version_tuple, filename, needs_rename, new_name)
    candidates = []
    for filename in apks:
        m = short_pat.match(filename)
        if m:
            candidates.append((parse_version(m.group(1)), filename, False, filename))
            continue
        for pat in apkm_pats:
            m = pat.match(filename)
            if not m:
                vm = re.search(r'(com\.facebook\.orca).*?_(\d+\.\d+\.\d+\.\d+)', filename, re.I)
                if filename.lower().endswith("_apkmirror.com.apk") and vm:
                    m = vm
                else:
                    continue
            ver = m.group(2)
            new_name = f"com.facebook.orca_{ver}.com.apk"
            candidates.append((parse_version(ver), filename, True, new_name))
            break

    if not candidates:
        print("  [APK]: No Facebook Messenger APK matched")
        return None

    # Pick highest version
    candidates.sort(key=lambda x: x[0], reverse=True)
    ver_tuple, filename, needs_rename, new_name = candidates[0]
    ver_str = ".".join(str(x) for x in ver_tuple)
    print(f"  [APK]: Selected version {ver_str} — {filename}")

    if not needs_rename:
        return filename

    old_path = os.path.join(DEST, filename)
    new_path = os.path.join(DEST, new_name)
    if os.path.exists(new_path):
        print(f"  [APK]: {new_name} already exists — using it")
        os.remove(old_path)
        return new_name
    print(f"  [APK]: {filename[:60]}")
    print(f"      → {new_name}")
    os.rename(old_path, new_path)
    return new_name

def resolve_apk():
    global APK_IN
    detected = find_and_rename_apkmirror_apk()
    if detected:
        APK_IN = detected
        print(f"[APK]: Using {APK_IN}")
        return
    print("\n[ERROR]: No valid APK found.")
    print("  Download from: https://www.apkmirror.com/apk/facebook-2/messenger/")
    print("  - nodpi single APK variant — script will auto-rename it")
    sys.exit(1)

# ─── GITHUB API ───────────────────────────────────────────────────────────────
def get_releases(repo):
    def _fetch():
        with open_url(f"https://api.github.com/repos/{repo}/releases", timeout=15) as r:
            return json.loads(r.read())
    return with_retry(_fetch)

def pick_release(releases):
    for rel in releases:
        if rel.get("prerelease"): return rel
    for rel in releases:
        if not rel.get("draft"): return rel
    return releases[0]

def find_asset(assets, keyword):
    for a in assets:
        if keyword in a["name"]:
            return a["name"], a["browser_download_url"], a.get("size", 0)
    return None, None, 0

# ─── DOWNLOAD ─────────────────────────────────────────────────────────────────
def download(name, url, expected_size=0):
    dest = os.path.join(DEST, name)

    # Try sidecar SHA256
    sha256 = fetch_sha256(url)
    if sha256 and os.path.exists(dest):
        if sha256_file(dest) == sha256:
            print(f"  [SKIP]: {name} ({human_size(os.path.getsize(dest))}) ✓")
            return
        else:
            print(f"  [WARN]: Checksum mismatch — redownloading {name}")
            os.remove(dest)
    elif os.path.exists(dest):
        if expected_size and os.path.getsize(dest) == expected_size:
            print(f"  [SKIP]: {name} ({human_size(os.path.getsize(dest))})")
            return

    resume_from = os.path.getsize(dest) if os.path.exists(dest) else 0
    label = f"({human_size(expected_size)})" if expected_size else "(unknown size)"
    print(f"  {'[RESUME]' if resume_from else '[DOWNLOAD]'}: {name} {label}")

    def _dl():
        dl = resume_from
        with open_url(url, timeout=60, resume_from=resume_from) as r, \
             open(dest, "ab" if resume_from else "wb") as f:
            total = int(r.headers.get("Content-Length", 0)) + resume_from
            while True:
                buf = r.read(8192)
                if not buf: break
                f.write(buf)
                dl += len(buf)
                if total:
                    print(f"\r    {human_size(dl)} / {human_size(total)} ({dl/total*100:.1f}%)", end="", flush=True)
        return dl

    dl = with_retry(_dl)
    print(f"\n  [DONE]: {name} ({human_size(dl)})")

    if sha256:
        if sha256_file(dest) != sha256:
            print(f"  [ERROR]: Checksum mismatch for {name}.")
            os.remove(dest)
            sys.exit(1)
        print(f"  [✓]: Checksum verified")

def is_valid_zip(path):
    try:
        with zipfile.ZipFile(path, "r") as z:
            z.infolist()
        return True
    except Exception:
        return False

def find_local(keyword, ext):
    for f in os.listdir(DEST):
        if keyword in f and f.endswith(ext):
            full = os.path.join(DEST, f)
            if ext in (".jar", ".rvp") and not is_valid_zip(full):
                print(f"  [WARN]: {f} is corrupt — removing")
                os.remove(full)
                return None
            return f
    return None

def extract_aapt2():
    jar = os.path.join(DEST, AAPT2_JAR_NAME.get(SYSTEM, "aapt2-windows.jar"))
    exe = os.path.join(DEST, AAPT2_BIN)
    if os.path.exists(exe):
        print(f"  [SKIP]: {AAPT2_BIN} ({human_size(os.path.getsize(exe))})")
        return
    print(f"  [EXTRACT]: Extracting {AAPT2_BIN}...")
    with zipfile.ZipFile(jar, "r") as z:
        candidates = [n for n in z.namelist() if "aapt2" in n.lower()]
        if not candidates:
            print(f"  [ERROR]: {AAPT2_BIN} not found in JAR.")
            sys.exit(1)
        z.extract(candidates[0], DEST)
        extracted = os.path.join(DEST, candidates[0])
        if extracted != exe:
            shutil.move(extracted, exe)
        if SYSTEM != "Windows":
            os.chmod(exe, 0o755)
        print(f"  [DONE]: {AAPT2_BIN} ({human_size(os.path.getsize(exe))})")

# ─── ENSURE LATEST (CLI + PATCHES) ───────────────────────────────────────────
def ensure_latest(keyword, ext, asset_keyword, repo, label):
    """Download if missing. Update if newer version available."""
    local = find_local(keyword, ext)
    try:
        rel = pick_release(get_releases(repo))
    except Exception as e:
        if local:
            print(f"  [WARN]: Cannot check {label} updates ({e}). Using {local}")
            return local
        print(f"  [ERROR]: Cannot fetch {label} and no local file exists.")
        sys.exit(1)

    pre = "PRE-RELEASE" if rel.get("prerelease") else "STABLE"
    name, url, size = find_asset(rel["assets"], asset_keyword)

    if not name:
        if local:
            print(f"  [WARN]: No asset found. Using {local}")
            return local
        print(f"  [ERROR]: No matching asset for {label}")
        sys.exit(1)

    if local == name:
        print(f"  [OK]: {name} [{pre}] — up-to-date")
        return local
    if local and local != name:
        print(f"  [UPDATE]: {local} → {name} [{pre}]")
        os.remove(os.path.join(DEST, local))
    else:
        print(f"  [MISSING]: {name} [{pre}]")

    download(name, url, size)
    return name

# ─── SETUP ────────────────────────────────────────────────────────────────────
def setup():
    print("\n[SETUP]: Checking dependencies...")

    # CLI and patches: always check for updates
    cli_name     = ensure_latest("revanced-cli", ".jar", "all.jar", "ReVanced/revanced-cli",     "ReVanced CLI")
    patches_name = ensure_latest("patches",       ".rvp", ".rvp",   "ReVanced/revanced-patches", "ReVanced Patches")

    # Other tools: download once
    apktool_name = find_local("apktool_", ".jar")
    uber_name    = find_local("uber-apk-signer", ".jar")
    aapt2_exists = os.path.exists(os.path.join(DEST, AAPT2_BIN))

    missing = []
    if not apktool_name: missing.append("Apktool")
    if not uber_name:    missing.append("uber-apk-signer")
    if not aapt2_exists: missing.append(AAPT2_BIN)

    if missing:
        print(f"[SETUP]: Missing: {', '.join(missing)}. Downloading...")

        if not apktool_name:
            print("[INFO]: Fetching Apktool...")
            rel = pick_release(get_releases("iBotPeaches/Apktool"))
            print(f"  [{'PRE-RELEASE' if rel.get('prerelease') else 'STABLE'}]: {rel['tag_name']}")
            apktool_name, url, size = find_asset(rel["assets"], "apktool_")
            if apktool_name: download(apktool_name, url, size)

        if not uber_name:
            print("[INFO]: Fetching uber-apk-signer...")
            rel = pick_release(get_releases("patrickfav/uber-apk-signer"))
            print(f"  [{'PRE-RELEASE' if rel.get('prerelease') else 'STABLE'}]: {rel['tag_name']}")
            uber_name, url, size = find_asset(rel["assets"], ".jar")
            if uber_name: download(uber_name, url, size)

        if not aapt2_exists:
            aapt2_url = AAPT2_URLS.get(SYSTEM, AAPT2_URLS["Windows"])
            jar_name  = AAPT2_JAR_NAME.get(SYSTEM, "aapt2-windows.jar")
            print(f"[INFO]: Downloading aapt2 for {SYSTEM}...")
            download(jar_name, aapt2_url)
            extract_aapt2()
    else:
        print("[SETUP]: All other dependencies found.")

    return cli_name, patches_name, apktool_name, uber_name

# ─── PATCH SELECTION ──────────────────────────────────────────────────────────
def select_patches():
    print(f"[PATCHES]: Applying {len(PATCHES)} patches.")
    return list(PATCHES)

# ─── WATCHER ──────────────────────────────────────────────────────────────────
stop_watcher = threading.Event()

def watch_and_clean_dummies():
    watch_path = os.path.join(DEST, TEMP_DIR)
    print("[WATCHER]: Waiting for temp directory...")
    while not os.path.exists(watch_path) and not stop_watcher.is_set():
        time.sleep(0.3)
    print("[WATCHER]: Monitoring invalid resources...")
    total_deleted = 0
    while not stop_watcher.is_set():
        dummies = glob.glob(os.path.join(watch_path, "**", "APKTOOL_DUMMYVAL_*.xml"), recursive=True)
        for f in dummies:
            try:
                os.remove(f)
                total_deleted += 1
            except Exception:
                pass
        if dummies:
            print(f"[WATCHER]: Removed {len(dummies)} DUMMYVAL files (total: {total_deleted})")
        res_path = os.path.join(watch_path, "patcher", "apk", "res")
        if os.path.exists(res_path):
            for entry in os.listdir(res_path):
                if ".2" in entry:
                    try:
                        shutil.rmtree(os.path.join(res_path, entry))
                        print(f"[WATCHER]: Removed .2 dir: {entry}")
                    except Exception:
                        pass
        time.sleep(0.2)
    print(f"[WATCHER]: Stopped. Total deleted: {total_deleted}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[ENV]: Platform — {SYSTEM} ({platform.machine()})")

    check_java()
    resolve_apk()
    verify_apk(os.path.join(DEST, APK_IN))
    check_disk_space(os.path.join(DEST, APK_IN))

    # Generate timestamped output filename
    now = datetime.now()
    PATCHED_APK = now.strftime("%Y-%m-%d_%I-%M-%S_%p-messenger.apk")

    cli_name, patches_name, apktool_name, uber_name = setup()
    # apktool_name and uber_name reserved for future manifest automation

    patches = select_patches()
    if not patches:
        print("[ERROR]: No patches selected. Exiting.")
        sys.exit(1)

    for path in [TEMP_DIR, PATCHED_APK]:
        if os.path.isdir(path): shutil.rmtree(path)
        elif os.path.isfile(path): os.remove(path)
    print("[CLEANUP]: Done.")

    enable_flags = []
    for patch in patches:
        enable_flags += ["-e", patch]

    watcher = threading.Thread(target=watch_and_clean_dummies, daemon=True)
    watcher.start()

    print("\n[PATCH]: Starting ReVanced patcher...")
    try:
        subprocess.run([
            "java",
            "-Dorg.slf4j.simpleLogger.defaultLogLevel=debug",
            "-jar", cli_name,
            "patch",
            "-p", patches_name,
            "-b",
            "--exclusive",
            *enable_flags,
            "--custom-aapt2-binary", AAPT2_BIN,
            "--temporary-files-path", TEMP_DIR,
            "--out", PATCHED_APK,
            APK_IN
        ], check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR]: Patch failed with exit code {e.returncode}")
        if e.stderr:
            print(f"  stderr: {e.stderr[:500]}")
        stop_watcher.set()
        watcher.join(timeout=5.0)
        sys.exit(1)

    stop_watcher.set()
    watcher.join(timeout=5.0)

    print(f"\n[DONE]: {PATCHED_APK}")
    print("\n[NEXT STEPS - MT Manager]:")
    print("  1. Copy final-messenger-apk.apk to Android device")
    print("  2. MT Manager → open APK → AndroidManifest.xml as String Pool")
    print("  3. Replace: com.facebook.permission.prod.FB_APP_COMMUNICATION")
    print("          → app.facebook.permission.prod.FB_APP_COMMUNICATION")
    print("  4. Replace: com.facebook.receiver.permission.Access")
    print("          → app.facebook.receiver.permission.Access")
    print("  5. Save → Sign → Install")