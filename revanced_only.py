"""
revanced_only.py — Auto-setup + ReVanced patcher for Facebook Messenger.

1. Validates environment (Java version, disk space, platform)
2. Checks dependencies, downloads missing ones with retry + resume + checksum
3. Interactive patch selection (skip with -y flag)
4. Runs ReVanced patch with DUMMYVAL/.2 directory watcher
5. Outputs final-messenger-apk.apk for MT Manager manifest fix + signing

NOTE: Base APK must be downloaded manually from APKMirror:
https://www.apkmirror.com/apk/facebook-2/messenger/
Download the nodpi single APK variant and place it in this folder.

Usage:
  python revanced_only.py          # interactive patch selection
  python revanced_only.py -y       # use default patches, no prompts
"""

import subprocess
import urllib.request
import urllib.error
import os
import sys
import threading
import time
import glob
import shutil
import zipfile
import json
import hashlib
import platform
import ssl
import re

# ─── CONFIG ───────────────────────────────────────────────────────────────────
APK_IN      = "com.facebook.orca_550.0.0.45.63.com.apk"
PATCHED_APK = "final-messenger-apk.apk"
TEMP_DIR    = "messenger_revanced-temporary-files"
DEST        = os.getcwd()

JAVA_MIN_VERSION = 11

PATCHES = [
    "Hide inbox ads",
    "Hide inbox subtabs",
    "Remove Meta AI",
    "Hide Facebook button",
    "Disable Pairip license check",
    "Disable Play Integrity",
    "Prevent screenshot detection",
]

SYSTEM    = platform.system()
AAPT2_BIN = "aapt2.exe" if SYSTEM == "Windows" else "aapt2"

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

# ─── HTTPS CONTEXT ────────────────────────────────────────────────────────────
SSL_CTX = ssl.create_default_context()

def open_url(url, timeout=30, resume_from=0):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "revanced-patcher/1.0")
    if resume_from > 0:
        req.add_header("Range", f"bytes={resume_from}-")
    return urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout)

# ─── RETRY LOGIC ──────────────────────────────────────────────────────────────
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
    """Check ZIP magic bytes to confirm file is a valid APK."""
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic != b"PK\x03\x04":
        print(f"[ERROR]: {path} does not appear to be a valid APK (bad magic bytes).")
        sys.exit(1)
    print(f"[ENV]: APK magic bytes OK ✓")

def check_disk_space(apk_path):
    """Require 3x APK size + 200MB buffer for tools."""
    apk_size = os.path.getsize(apk_path) if os.path.exists(apk_path) else 0
    required_mb = max(500, int(apk_size * 3 / (1024 * 1024)) + 200)
    stat = shutil.disk_usage(DEST)
    free_mb = stat.free / (1024 * 1024)
    if free_mb < required_mb:
        print(f"[ERROR]: Not enough disk space. Need ~{required_mb}MB, have {free_mb:.0f}MB.")
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
            if major < JAVA_MIN_VERSION:
                print(f"[ERROR]: Java {major} detected. ReVanced requires Java {JAVA_MIN_VERSION}+.")
                print("  Download: https://adoptium.net")
                sys.exit(1)
            print(f"[ENV]: Java {major} detected — OK")
        else:
            print(f"[WARN]: Could not parse Java version. Output: {output.strip()[:80]}")
    except FileNotFoundError:
        print("[ERROR]: Java not found. Install from https://adoptium.net")
        sys.exit(1)

# ─── GITHUB API ───────────────────────────────────────────────────────────────
def get_releases(repo):
    def _fetch():
        with open_url(f"https://api.github.com/repos/{repo}/releases", timeout=15) as r:
            return json.loads(r.read())
    return with_retry(_fetch)

def pick_release(releases):
    for rel in releases:
        if rel.get("prerelease"):
            return rel
    for rel in releases:
        if not rel.get("draft"):
            return rel
    return releases[0]

def find_asset(assets, keyword):
    for a in assets:
        if keyword in a["name"]:
            return a["name"], a["browser_download_url"], a.get("size", 0)
    return None, None, 0

# ─── DOWNLOAD WITH RESUME + CHECKSUM ─────────────────────────────────────────
def download(name, url, expected_size=0, expected_sha256=None):
    dest = os.path.join(DEST, name)

    if os.path.exists(dest):
        existing_size = os.path.getsize(dest)
        if expected_sha256:
            if sha256_file(dest) == expected_sha256:
                print(f"  [SKIP]: {name} ({human_size(existing_size)}) ✓ checksum OK")
                return
            else:
                print(f"  [WARN]: {name} checksum mismatch — redownloading")
                os.remove(dest)
        elif expected_size and existing_size == expected_size:
            print(f"  [SKIP]: {name} ({human_size(existing_size)})")
            return

    if expected_sha256 is None:
        expected_sha256 = fetch_sha256(url)
        if expected_sha256:
            print(f"  [INFO]: SHA-256 sidecar found for {name}")

    resume_from = os.path.getsize(dest) if os.path.exists(dest) else 0
    label = f"({human_size(expected_size)})" if expected_size else "(unknown size)"
    if resume_from == 0:
        print(f"  [DOWNLOAD]: {name} {label}")
    else:
        print(f"  [RESUME]: {name} from {human_size(resume_from)}")

    def _download():
        mode = "ab" if resume_from > 0 else "wb"
        downloaded = resume_from
        with open_url(url, timeout=60, resume_from=resume_from) as r, open(dest, mode) as f:
            total = int(r.headers.get("Content-Length", 0)) + resume_from
            while True:
                buf = r.read(8192)
                if not buf:
                    break
                f.write(buf)
                downloaded += len(buf)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r    {human_size(downloaded)} / {human_size(total)} ({pct:.1f}%)", end="", flush=True)
        return downloaded

    downloaded = with_retry(_download)
    print(f"\n  [DONE]: {name} ({human_size(downloaded)})")

    if expected_sha256:
        actual = sha256_file(dest)
        if actual != expected_sha256:
            print(f"  [ERROR]: Checksum mismatch for {name}. File may be corrupt.")
            os.remove(dest)
            sys.exit(1)
        print(f"  [✓]: Checksum verified")

def extract_aapt2():
    jar_name = AAPT2_JAR_NAME.get(SYSTEM, "aapt2-windows.jar")
    jar = os.path.join(DEST, jar_name)
    exe = os.path.join(DEST, AAPT2_BIN)
    if os.path.exists(exe):
        print(f"  [SKIP]: {AAPT2_BIN} ({human_size(os.path.getsize(exe))})")
        return
    print(f"  [EXTRACT]: Extracting {AAPT2_BIN}...")
    with zipfile.ZipFile(jar, "r") as z:
        candidates = [n for n in z.namelist() if "aapt2" in n.lower()]
        if candidates:
            z.extract(candidates[0], DEST)
            extracted = os.path.join(DEST, candidates[0])
            if extracted != exe:
                shutil.move(extracted, exe)
            if SYSTEM != "Windows":
                os.chmod(exe, 0o755)
            print(f"  [DONE]: {AAPT2_BIN} ({human_size(os.path.getsize(exe))})")
        else:
            print(f"  [ERROR]: {AAPT2_BIN} not found in JAR.")
            sys.exit(1)

def is_valid_zip(path):
    """Check if file is a valid ZIP/JAR/RVP."""
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
                print(f"  [WARN]: {f} is corrupt or outdated — deleting and redownloading")
                os.remove(full)
                return None
            return f
    return None

# ─── INTERACTIVE PATCH SELECTION ─────────────────────────────────────────────
def select_patches():
    print(f"[PATCHES]: Using default patches.")
    return list(PATCHES)

# ─── SETUP ────────────────────────────────────────────────────────────────────
def setup():
    print("\n[SETUP]: Checking dependencies...")

    cli_name     = find_local("revanced-cli", ".jar")
    patches_name = find_local("patches", ".rvp")
    apktool_name = find_local("apktool_", ".jar")
    uber_name    = find_local("uber-apk-signer", ".jar")
    aapt2_exists = os.path.exists(os.path.join(DEST, AAPT2_BIN))

    missing = []
    if not cli_name:     missing.append("ReVanced CLI")
    if not patches_name: missing.append("ReVanced Patches")
    if not apktool_name: missing.append("Apktool")
    if not uber_name:    missing.append("uber-apk-signer")
    if not aapt2_exists: missing.append(AAPT2_BIN)

    if not missing:
        print("[SETUP]: All dependencies found.")
        return cli_name, patches_name, apktool_name, uber_name

    print(f"[SETUP]: Missing: {', '.join(missing)}. Downloading...")

    if not cli_name:
        print("[INFO]: Fetching ReVanced CLI...")
        rel = pick_release(get_releases("ReVanced/revanced-cli"))
        print(f"  [{'PRE-RELEASE' if rel.get('prerelease') else 'STABLE'}]: {rel['tag_name']}")
        cli_name, url, size = find_asset(rel["assets"], "all.jar")
        if cli_name: download(cli_name, url, size)

    if not patches_name:
        print("[INFO]: Fetching ReVanced Patches...")
        rel = pick_release(get_releases("ReVanced/revanced-patches"))
        print(f"  [{'PRE-RELEASE' if rel.get('prerelease') else 'STABLE'}]: {rel['tag_name']}")
        patches_name, url, size = find_asset(rel["assets"], ".rvp")
        if patches_name: download(patches_name, url, size)

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

    return cli_name, patches_name, apktool_name, uber_name

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

    if not os.path.exists(os.path.join(DEST, APK_IN)):
        print(f"\n[ERROR]: Base APK not found: {APK_IN}")
        print("  Download from: https://www.apkmirror.com/apk/facebook-2/messenger/")
        print("  - nodpi single APK variant")
        print(f"  - Rename to: {APK_IN}")
        sys.exit(1)

    verify_apk(os.path.join(DEST, APK_IN))
    check_disk_space(os.path.join(DEST, APK_IN))

    cli_name, patches_name, apktool_name, uber_name = setup()
    # apktool_name and uber_name are downloaded for future manifest patching
    # automation (apktool decode/rebuild + uber-apk-signer signing pipeline)

    patches = select_patches()
    if not patches:
        print("[ERROR]: No patches selected. Exiting.")
        sys.exit(1)

    for path in [TEMP_DIR, PATCHED_APK]:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
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