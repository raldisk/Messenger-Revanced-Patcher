# Messenger ReVanced Patcher

A Python script that automates applying ReVanced patches to Facebook Messenger (com.facebook.orca) on Windows.

---

## What It Does

- Applies selected ReVanced patches to the Messenger APK
- Handles Messenger's broken resource table (`APKTOOL_DUMMYVAL` / `.2` directory issues) automatically via a background watcher
- Outputs a patched APK ready for manifest fixing and signing

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

## Dependencies

Place all files in the **same folder** as the script before running.

### 1. Java (JDK 11+)
Required to run all `.jar` tools.
- https://adoptium.net

### 2. ReVanced CLI
- Filename: `revanced-cli-6.0.0-dev.2-all.jar`
- Download: https://github.com/ReVanced/revanced-cli/releases

### 3. ReVanced Patches
- Filename: `patches-6.0.0-dev.14.rvp`
- Download: https://github.com/ReVanced/revanced-patches/releases

### 4. aapt2.exe
Required for resource compilation. Extract `aapt2.exe` from the JAR using 7-Zip.
- Download from Google Maven:
  https://maven.google.com/web/index.html#com.android.tools.build:aapt2
- Find the latest version, download the `-windows.jar`, extract `aapt2.exe`

### 5. Base APK
- Package: `com.facebook.orca`
- Version tested: `550.0.0.45.63`
- Download from APKMirror: https://www.apkmirror.com/apk/facebook-2/messenger/
- **Important:** Download the **single APK (nodpi)** variant, NOT the bundle

### 6. Keystore
See [Creating a Keystore](#creating-a-keystore) section below.

---

## File Structure

```
messenger-rebuild/
├── revanced_only.py
├── revanced-cli-6.0.0-dev.2-all.jar
├── patches-6.0.0-dev.14.rvp
├── aapt2.exe
├── Manager.keystore
└── com.facebook.orca_550.0.0.45.63.com.apk
```

---

## Usage

```powershell
python revanced_only.py
```

Output: `final-messenger-apk.apk`

---

## Creating a Keystore

You can generate a keystore using ReVanced CLI directly:

```bash
java -jar revanced-cli-6.0.0-dev.2-all.jar utility keystore --keystore Manager.keystore --keystore-entry-alias "ReVanced Key" --keystore-password ReVanced --keystore-entry-password ReVanced
```

This creates `Manager.keystore` in the current directory with the default ReVanced credentials. Keep this file safe — you need the **same keystore** every time you repatch, otherwise Android will reject the update due to signature mismatch.

---

## Post-Patch: Manifest Fix (MT Manager Method)

After the script outputs `final-messenger-apk.apk`, the APK cannot be installed directly due to a permission conflict. Fix it using **MT Manager** on Android:

> This method is recommended over the full apktool decode/rebuild pipeline as it is significantly faster and less resource intensive.

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

Facebook Messenger declares custom permissions using its own package name (`com.facebook.*`). When a patched APK tries to declare the same permissions as a different signer, Android rejects the install. Renaming the permission strings avoids the conflict.

---

## Credits

- **MT Manager manifest fix method** — originally documented by [@reisxd](https://github.com/ReVanced/revanced-patches/issues/1063#issuecomment-1854976122) in the ReVanced patches issue tracker

---

## Notes

- Patching does **not** require an internet connection
- The watcher thread runs continuously during patching to delete invalid `.2` resource directories that cause aapt2 to fail
- `APKTOOL_DUMMYVAL` files are a known apktool limitation with Messenger's split resource table

---

## License

MIT License — see [LICENSE](LICENSE)
