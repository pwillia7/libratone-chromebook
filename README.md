# Libratone Chromebook Patch

Run the Libratone Android app on ChromeOS/ARC with Libratone Bluetooth speakers that pair successfully in ChromeOS but never appear as connected inside the app.

This project does **not** distribute the Libratone app or any Libratone APKs. You provide your own Libratone XAPK/APK set; the patcher modifies it locally on your machine.

> **Beta branch:** this branch includes the stable ChromeOS compatibility fixes plus additional UX/robustness patches described below. It is intended for testing before those changes are considered for `main`.

## What this fixes

ChromeOS owns the real Bluetooth audio connection while Android/ARC may expose the same speaker as bonded without reporting the normal Android A2DP `STATE_CONNECTED` state that Libratone expects.

The beta patch set makes five guarded changes to Libratone 8.3.1:

1. Treat bonded Libratone devices as connected candidates when ARC reports them as bonded but not Android-profile-connected.
2. Seed Libratone's internal classic-connected speaker manager from bonded Libratone products instead of waiting for an A2DP/headset `CONNECTION_STATE_CHANGED` broadcast that ARC may never deliver.
3. Relax Libratone's SPP UUID-count gate for devices already recognized as Libratone products, because ARC may expose an incomplete SDP UUID list. This also removes the developer-facing `uuids null or Only one` failure path.
4. Merge bonded Libratone products into the app's Bluetooth discovery backing list so Chromebook discovery remains useful when ARC does not deliver every classic `ACTION_FOUND` callback.
5. Remove the PLUS 1 screen's 500 ms `Thread.sleep()` on EventBus's main/UI thread.

The patch is intentionally version-specific and aborts if the expected smali structures are not found.

## Tested setup

- ChromeOS with Android/ARC
- Android 13 / API 33 inside ARC
- Libratone app 8.3.1 (`versionCode 831`)
- Libratone ONE speakers
- ADB target: `arc:5555`

The two stable compatibility fixes were tested on this setup. The additional beta fixes should be treated as experimental until exercised on-device.

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

On the `beta` branch, `patch.sh` runs `beta_patcher.py`, which first applies the stable compatibility layer from `patcher.py` and then applies the additional beta patches.

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

The beta flow:

1. Extracts your XAPK.
2. Verifies package/version metadata is consistent with Libratone 8.3.1 / 831.
3. Decodes the base APK with Apktool.
4. Applies the two stable ChromeOS/ARC smali patches.
5. Applies three additional guarded beta smali patches for UUID handling, discovery fallback, and PLUS 1 UI-thread behavior.
6. Lets Apktool rebuild the modified `classes6.dex`.
7. Copies the untouched original base APK and replaces only `classes6.dex`.
8. Removes stale signatures.
9. Runs `zipalign`.
10. Signs the base APK and all split APKs with a locally generated signing key.
11. Writes the installable set to `output/`.

The resource table is deliberately preserved from the original APK. Modern Libratone resources reference private Android framework colors that do not round-trip cleanly through Apktool/aapt2, so rebuilding the entire APK is unnecessary and less reliable for this code-only patch.

## Beta test checklist

After installing a beta build, verify all of these before considering it stable:

- The app launches normally with no `VerifyError`/crash.
- A ChromeOS-bonded Libratone ONE still appears on the home screen.
- Speaker controls still work.
- PLUS 1 can discover and pair the second ONE after forgetting/disconnecting that second speaker from ChromeOS first.
- Opening and refreshing the PLUS 1 picker does not create duplicate speaker rows.
- Pairing no longer produces the developer-facing `uuids null or Only one` dialog.
- PLUS 1 interaction feels responsive and no regressions appear after removing the 500 ms UI-thread sleep.

Useful beta log filter:

```bash
adb -s arc:5555 logcat -v time | \
  grep -iE 'AndroidRuntime|VerifyError|BlueToothUtil|LbtBTUtil|BTSelectSlave|C4:67:B5|SPP|BluetoothGatt'
```

## Safety / limitations

- This is an unofficial compatibility patch and is not affiliated with Libratone.
- No proprietary Libratone APK is included in this repository.
- The patch is tested against one specific app version and intentionally fails closed on unexpected code layouts.
- Beta changes alter additional Bluetooth-selection logic beyond the minimum stable fix; keep `main` available as the fallback.
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
