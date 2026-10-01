# Libratone Chromebook Patch

Run the Libratone Android app on ChromeOS/ARC with Libratone Bluetooth speakers that pair successfully in ChromeOS but never appear as connected inside the app.

This project does **not** distribute the Libratone app or any Libratone APKs. You provide your own Libratone XAPK/APK set; the patcher modifies it locally on your machine.

## What this fixes

ChromeOS owns the real Bluetooth audio connection. Android/ARC sees the speaker as bonded, and mirrors ChromeOS's *physical* (ACL) link state into `BluetoothDevice.isConnected()` and `ACTION_ACL_CONNECTED` / `ACTION_ACL_DISCONNECTED`, but it never reports an Android A2DP profile connection or sends the A2DP/headset `CONNECTION_STATE_CHANGED` broadcast that Libratone waits for. Without that broadcast the app never learns a speaker is connected.

The patch makes one guarded compatibility change to Libratone 8.3.1 (in `classes6.dex`):

- **Sync Libratone's internal "classic-connected" speaker list with the speakers ARC reports as actually connected.** A new `BlueToothUtil.arcSyncConnectedProducts()` adds bonded Libratone products whose `isConnected()` is true and removes ones that are no longer connected. It runs where the app registers its Bluetooth receiver, and again (debounced) whenever ARC sends an ACL connect/disconnect broadcast, via a small added class `ArcBtCompat` ([`patches/ArcBtCompat.smali`](patches/ArcBtCompat.smali)).

`LbtBTUtil` is left unmodified; the patcher only verifies its expected layout.

The patch is intentionally version-specific and aborts if the expected smali structures are not found.

### Change from the original patch set (solo-speaker regression)

The first version of this patcher made two changes: it (1) replaced `LbtBTUtil`'s `isConnected()` check with "MAC starts with `C4:67:B5`", and (2) seeded the classic-connected list with **every bonded** Libratone speaker. With two speakers bonded, that caused a real regression:

- The app's auto-connect (`findTheRightDeviceToConnectSPP()` → `findFirst()`) opened its SPP control channel to whichever bonded speaker the hash map returned first — often **not** the speaker ChromeOS was playing to. That made the Chromebook repeatedly page the other speaker.
- The app's single SPP slot was then tied up on the wrong speaker, so tapping **Add** on the speaker that was actually connected failed silently (`isSppAvailable: false`).
- Powered-off speakers still showed up as "nearby" from cached data.

Patch 1 was based on a wrong assumption: on current ARC (Android 13), reflecting `BluetoothDevice.isConnected()` from a normal app works and accurately reports which speaker ChromeOS is connected to (verified with a standalone probe app). The fixed patch uses that signal instead of "bonded == connected".

If you previously installed a build from the original patch set, re-run the patcher and `./install.sh`; with the same signing key it installs as an in-place update.

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

## PLUS 1 / stereo pairing notes

A useful ChromeOS-specific quirk discovered while testing:

1. Get the first speaker recognized in Libratone.
2. If the second speaker has already been paired directly to ChromeOS, **disconnect/forget the second speaker in ChromeOS first**.
3. Add the second speaker through Libratone's **PLUS 1** flow.

In testing, leaving the second speaker already connected to ChromeOS prevented the PLUS 1 flow from taking ownership of the pairing correctly.

### PLUS 1 state lives in the speaker firmware

The PLUS 1 (TWS stereo) relationship is stored **inside the speakers**, not in the app or ChromeOS. The app drives it with Libratone Bluetooth commands sent over the speaker's SPP control channel (service 6):

| Command | Meaning |
|---|---|
| `Group_State` (6/1) | Query: `0` = standalone, `1`/`3` = master, `2` = slave |
| `Create_Group` (6/4) | Sent to the master with the second speaker's MAC |
| `Waiting_for_Group` (6/5) | Puts a speaker into "join a group" mode |
| `Leave_Group` (6/6) | What the app's **Unlink** button sends; dissolves the group |

Because the state is in the firmware, deleting a speaker in the Libratone app, forgetting it in ChromeOS, restarting the Chromebook, or closing the app does **not** clear it.

### Symptoms we saw and what they meant

- **A speaker pairs in ChromeOS, then drops the link after 2–4 seconds, plays no audio, and shows "looking for a known host" — even with the Libratone app closed.** The speaker's own stored state was stuck. Only a speaker **factory reset** fixed it.
- **The app discovers a speaker but "Add" silently does nothing.** Either the app has no SPP control channel to that speaker (it isn't actually connected; check `arcSync … connected=` in the log), or the SPP slot is busy with another speaker (the old patch set's bug).
- **PLUS 1 fails with "Please disconnect the other product connected with X before 'plus 1'".** The master speaker answered `Create_Group` with error code `3` (it refuses immediately, without contacting the second speaker). In our case `Leave_Group` alone didn't clear it; factory-resetting both speakers did.
- **PLUS 1 fails with "Failed. Please try again."** The master accepted `Create_Group` (`err=0`), but the speaker-to-speaker link didn't complete within the app's 30-second timeout. Make sure the second speaker is in setup mode (lights running side to side) and not paired to/connected to ChromeOS or another phone.

### Recovering a stuck speaker

1. Forget the speaker in ChromeOS Bluetooth settings.
2. Factory reset the speaker. For the Libratone ONE we did not find an official ONE-specific procedure; the documented ZIPP/ZIPP Mini one (same Nightingale touch-panel generation) — **with the speaker on, hold the Nightingale and the power button together for ~10 seconds until the lights rotate** — is what's commonly used. A reset restores the default name ("Libratone ONE"), so two reset ONEs will share a name; tell them apart by MAC or by powering one off.
3. Pair the speaker alone in ChromeOS and confirm solo playback before trying PLUS 1. You can rename it in the Libratone app afterwards.

### Firmware updates over ARC

Speaker firmware updates (OTA over SPP) **are not reliable from ARC**. In testing, an update of a Libratone ONE (firmware 31 → 32) aborted after ~7% when the app's SPP write thread was interrupted; the speaker stayed on 31 and kept working. If you need to update speaker firmware, do it from a phone running the stock Libratone app. This patch does not modify firmware-update behavior.

## What the patcher actually does

The script:

1. Extracts your XAPK.
2. Verifies package/version metadata is consistent with Libratone 8.3.1 / 831.
3. Decodes the base APK with Apktool.
4. Verifies `LbtBTUtil`'s original `isConnected()` check and the connected-manager layout are present, then applies one guarded edit to `BlueToothUtil` and adds `ArcBtCompat.smali`.
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

Watch which speaker the patched app considers connected (one line per bonded Libratone speaker each sync):

```bash
adb -s arc:5555 logcat -v time | grep -E 'arcSync|ArcBtCompat'
```

Watch ChromeOS's physical link to a speaker as mirrored into ARC (useful for "connects then drops" problems, and works with the Libratone app closed):

```bash
adb -s arc:5555 logcat -v time | grep -iE 'OnPhysicalConnectionStateChanged|Bond State Change' | grep -i 'c4:67:b5'
```

Notes for deeper debugging:

- Libratone's own logging (`GTLog`) is compiled off in release builds (`GTLog.flag = false` in `classes5.dex`). Flipping that static field to `true` in a private debug build makes the app log its full SPP traffic, including `Group_State` / `Create_Group` responses, to logcat.
- `run-as com.libratone` is disabled on ARC, so app-private data (including the app's file logs) isn't readable without root.

## License

The patching scripts in this repository are released under the MIT License. Libratone software remains the property of its respective copyright holders.
