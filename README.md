# Messenger ReVanced Patcher

A single Python script that automatically downloads dependencies and applies ReVanced patches to Facebook Messenger (com.facebook.orca) on Windows.

---

## What It Does

- Checks for required tools — downloads any that are missing automatically
- Prefers pre-release versions of ReVanced CLI and Patches, falls back to stable
- Applies selected ReVanced patches to the Messenger APK
- Handles Messenger's broken resource table (`APKTOOL_DUMMYVAL` / `.2` directory issues) via a background watcher thread
- Outputs a patched APK ready for the MT Manager manifest fix

---

## Patches Applied

| Patch | Description |
|---|---|
| Hide inbox ads | Removes ads from the inbox |
| Hide inbox subtabs | Hides subtabs in the inbox |
| Remove Meta AI | Removes Meta AI button |
| Hide Facebook button | Hides the Facebook shortcut button |
| Disable Pairip license check | Bypasses Pairip license verification |
| Disable Play Integrity | Bypasses Play Integrity API checks |
| Disable Sentry telemetry | Disables Sentry crash/telemetry reporting |
| Export internal data documents provider | Enables internal data export provider |
| Prevent screenshot detection | Disables screenshot detection flag |

---

## Requirements

- Python 3.x
- Java JDK 11+ — https://adoptium.net
- Internet connection (first run only, for dependency downloads)

---

## Usage

### Step 1 — Add Base APK (manual)

APKMirror blocks automated downloads, so this must be done manually.

1. Go to: https://www.apkmirror.com/apk/facebook-2/messenger/
2. Download the **nodpi single APK** variant (not bundle)
3. Rename it to match `APK_IN` in `revanced_only.py`
4. Place it in the same folder as the script

### Step 2 — Run

```powershell
python revanced_only.py
```

On first run, the script will automatically download:
- ReVanced CLI (latest pre-release or stable)
- ReVanced Patches (latest pre-release or stable)
- Apktool
- uber-apk-signer
- aapt2.exe (extracted from Google Maven JAR)

On subsequent runs, existing files are detected and skipped.

Output: `final-messenger-apk.apk`

---

## Dependencies (Auto-downloaded)

| Tool | Source |
|---|---|
| ReVanced CLI | https://github.com/ReVanced/revanced-cli/releases |
| ReVanced Patches | https://github.com/ReVanced/revanced-patches/releases |
| Apktool | https://github.com/iBotPeaches/Apktool/releases |
| uber-apk-signer | https://github.com/patrickfav/uber-apk-signer/releases |
| aapt2.exe | https://maven.google.com/web/index.html#com.android.tools.build:aapt2 |

---

## File Structure

```
messenger-rebuild/
├── revanced_only.py
├── Manager.keystore              ← your signing keystore
└── com.facebook.orca_*.apk      ← base APK from APKMirror
```

After first run, downloaded tools will appear alongside the script.

---

## Creating a Keystore

Generate a signing keystore using ReVanced CLI:

```bash
java -jar revanced-cli-*.jar utility keystore --keystore Manager.keystore --keystore-entry-alias "ReVanced Key" --keystore-password ReVanced --keystore-entry-password ReVanced
```

Keep `Manager.keystore` safe — you need the **same keystore** every time you repatch. Android will reject updates signed with a different key.

---

## Post-Patch: Manifest Fix (MT Manager Method)

After patching, the APK cannot be installed directly due to a permission conflict. Fix it using **MT Manager** on Android:

> This method is recommended over the full apktool decode/rebuild pipeline — it is significantly faster and less resource intensive.

### Steps

1. Copy `final-messenger-apk.apk` to your Android device
2. Open **MT Manager** → navigate to the APK
3. Tap the APK → **View** → open `AndroidManifest.xml` as **String Pool**
4. Find and replace:
   - `com.facebook.permission.prod.FB_APP_COMMUNICATION`
   → `app.facebook.permission.prod.FB_APP_COMMUNICATION`
5. Find and replace:
   - `com.facebook.receiver.permission.Access`
   → `app.facebook.receiver.permission.Access`
6. Save and exit
7. Sign the APK using MT Manager's built-in signing (use your keystore)
8. Install

### Why This Is Needed

Facebook Messenger declares custom permissions using its own package name (`com.facebook.*`). When a patched APK tries to declare the same permissions under a different signer, Android rejects the install. Renaming the permission strings avoids this conflict.

---

## Notes

- Patching does **not** require an internet connection after first setup
- The background watcher thread continuously removes invalid `.2` resource directories and `APKTOOL_DUMMYVAL` files that cause aapt2 to fail during patching
- `APKTOOL_DUMMYVAL` files are a known apktool limitation with Messenger's split resource table

---

## Credits

- **MT Manager manifest fix method** — originally documented by [@reisxd](https://github.com/ReVanced/revanced-patches/issues/1063#issuecomment-1854976122) in the ReVanced patches issue tracker

---

## License

MIT License — see [LICENSE](LICENSE)
