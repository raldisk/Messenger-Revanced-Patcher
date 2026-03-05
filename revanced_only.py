import subprocess
import os
import threading
import time
import glob
import shutil

# CONFIG
APK_IN = "com.facebook.orca_550.0.0.45.63.com.apk"
REVANCED_CLI = "revanced-cli-6.0.0-dev.2-all.jar"
REVANCED_PATCHES = "patches-6.0.0-dev.14.rvp"
PATCHED_APK = "final-messenger-apk.apk"
TEMP_DIR = "messenger_revanced-temporary-files"

PATCHES = [
    "Hide inbox ads",
    "Hide inbox subtabs",
    "Remove Meta AI",
    "Hide Facebook button",
    "Disable Pairip license check",
    "Disable Play Integrity",
    "Disable Sentry telemetry",
    "Export internal data documents provider",
    "Prevent screenshot detection",
]

# Cleanup leftovers
for path in [TEMP_DIR, PATCHED_APK]:
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.isfile(path):
        os.remove(path)
print("[CLEANUP]: Done.")

enable_flags = []
for patch in PATCHES:
    enable_flags += ["-e", patch]

stop_watcher = threading.Event()

def watch_and_clean_dummies():
    watch_path = os.path.join(os.getcwd(), TEMP_DIR)
    print("[WATCHER]: Waiting for temp directory...")
    while not os.path.exists(watch_path) and not stop_watcher.is_set():
        time.sleep(0.3)
    print("[WATCHER]: Monitoring DUMMYVAL files...")
    total_deleted = 0
    while not stop_watcher.is_set():
        dummies = glob.glob(os.path.join(watch_path, "**", "APKTOOL_DUMMYVAL_*.xml"), recursive=True)
        if dummies:
            for f in dummies:
                try:
                    os.remove(f)
                    total_deleted += 1
                except Exception:
                    pass
            print(f"[WATCHER]: Removed {len(dummies)} files (total: {total_deleted})")
        time.sleep(0.2)
    print(f"[WATCHER]: Stopped. Total deleted: {total_deleted}")

watcher = threading.Thread(target=watch_and_clean_dummies, daemon=True)
watcher.start()

subprocess.run([
    "java",
    "-Dorg.slf4j.simpleLogger.defaultLogLevel=debug",
    "-jar", REVANCED_CLI,
    "patch",
    "-p", REVANCED_PATCHES,
    "-b",
    "--exclusive",
    *enable_flags,
    "--custom-aapt2-binary", "aapt2.exe",
    "--temporary-files-path", TEMP_DIR,
    "--out", PATCHED_APK,
    APK_IN
], check=True)

stop_watcher.set()
watcher.join()
print(f"Done: {PATCHED_APK} — now fix manifest with MT Manager, then sign.")
