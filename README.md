# Libratone Chromebook Patch

Run the Libratone Android app on ChromeOS/ARC with Libratone Bluetooth speakers that pair successfully in ChromeOS but never appear as connected inside the app.

This project does **not** distribute the Libratone app or any Libratone APKs. You provide your own Libratone XAPK/APK set; the patcher modifies it locally on your machine.

## What this fixes

ChromeOS owns the real Bluetooth audio connection while Android/ARC may expose the same speaker as bonded without reporting the normal Android A2DP `STATE_CONNECTED` state that Libratone expects.

The patch makes two small compatibility changes to Libratone 8.3.1:

1. Treat bonded Libratone devices as connected candidates when ARC reports them as bonded but not Android-profile-connected.
2. Seed Libratone's internal classic-connected speaker manager from bonded Libratone products instead of waiting for an A2DP/headset `CONNECTION_STATE_CHANGED` broadcast that ARC may never deliver.

The patch is intentionally version-specific and aborts if the expected smali structures are not found.

## Tested setup

- ChromeOS with Android/ARC
- Android 13 / API 33 inside ARC
- Libratone app 8.3.1 (`versionCode 831`)
- Libratone ONE speakers
- ADB target: `arc:5555`

Other versions may work only after updating the patch signatures. The script will not blindly patch unknown layouts.

## Requirements

You need these commands available:

- `java`
- `keytool`
- `python3`
- `unzip`
- `zip`
- `zipalign`
- `apksigner`
- `adb`

On Debian/Ubuntu/Crostini, a typical starting point is:

```bash
sudo apt update
sudo apt install -y default-jdk python3 unzip zip zipalign apksigner adb wget
```

## Usage

### 1. Obtain Libratone 8.3.1 yourself

Place your own Libratone 8.3.1 XAPK in a local directory. This repository does not provide it.

### 2. Patch it

```bash
./patch.sh /path/to/Libratone_v8.3.1.xapk
```

The first run downloads Apktool 3.0.2 from its official GitHub release and creates a local signing key under:

```text
~/.local/share/libratone-chromebook/signing.keystore
```

Keep that keystore. Future patched builds signed with the same key can be installed as updates over earlier patched builds.

Patched APKs are written to:

```text
output/
```

### 3. Install to ARC

Make sure ChromeOS Android debugging is enabled and ARC is visible:

```bash
adb devices
```

You should see `arc:5555`.

Then run:

```bash
./install.sh
```

The installer first tries an in-place update. If Android rejects it because a differently signed Libratone build is installed, it explains how to uninstall the existing package and rerun.

## PLUS 1 / stereo pairing note

A useful ChromeOS-specific quirk discovered while testing:

1. Get the first speaker recognized in Libratone.
2. If the second speaker has already been paired directly to ChromeOS, **disconnect/forget the second speaker in ChromeOS first**.
3. Add the second speaker through Libratone's **PLUS 1** flow.

In testing, leaving the second speaker already connected to ChromeOS prevented the PLUS 1 flow from taking ownership of the pairing correctly.

## What the patcher actually does

The script:

1. Extracts your XAPK.
2. Verifies package/version metadata is consistent with Libratone 8.3.1 / 831.
3. Decodes the base APK with Apktool.
4. Applies two exact, guarded smali edits.
5. Lets Apktool rebuild the modified `classes6.dex`.
6. Copies the untouched original base APK and replaces only `classes6.dex`.
7. Removes stale signatures.
8. Runs `zipalign`.
9. Signs the base APK and all split APKs with a locally generated signing key.
10. Writes the installable set to `output/`.

The resource table is deliberately preserved from the original APK. Modern Libratone resources reference private Android framework colors that do not round-trip cleanly through Apktool/aapt2, so rebuilding the entire APK is unnecessary and less reliable for this code-only patch.

## Safety / limitations

- This is an unofficial compatibility patch and is not affiliated with Libratone.
- No proprietary Libratone APK is included in this repository.
- The patch is tested against one specific app version and intentionally fails closed on unexpected code layouts.
- A future Libratone release may move or rewrite the relevant code.
- Uninstalling the app clears its local app data.

## Troubleshooting

Check ARC visibility:

```bash
adb devices
```

Inspect Libratone Bluetooth logs:

```bash
adb -s arc:5555 logcat -v time | \
  grep -iE 'BlueToothUtil|LbtBTUtil|Libratone|C4:67:B5|BluetoothGatt|SPP'
```

Inspect ARC's bonded devices:

```bash
adb -s arc:5555 shell dumpsys bluetooth_manager | \
  grep -iE 'Bonded devices|C4:67:B5' -A15
```

## License

The patching scripts in this repository are released under the MIT License. Libratone software remains the property of its respective copyright holders.
