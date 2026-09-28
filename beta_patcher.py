#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys

import patcher as stable


def method_bounds(s: str, method_name: str, descriptor: str) -> tuple[int, int, str]:
    pattern = re.compile(rf"(?m)^\.method[^\n]*\s{re.escape(method_name)}{re.escape(descriptor)}\s*$")
    matches = list(pattern.finditer(s))
    if len(matches) != 1:
        sys.exit(f"Beta guard failed: expected one {method_name}{descriptor}, found {len(matches)}")
    start = matches[0].start()
    end_marker = s.find("\n.end method", matches[0].end())
    if end_marker < 0:
        sys.exit(f"Beta guard failed: no .end method for {method_name}{descriptor}")
    end = end_marker + len("\n.end method")
    if end < len(s) and s[end] == "\n":
        end += 1
    return start, end, matches[0].group(0)


def patch_spp_uuid_gate(path: pathlib.Path) -> None:
    s = path.read_text()
    start, end, header = method_bounds(s, "isOurSppProduct", "(Landroid/bluetooth/BluetoothDevice;)Z")
    original = s[start:end]
    required = [
        "Landroid/bluetooth/BluetoothDevice;->getUuids()[Landroid/os/ParcelUuid;",
        "uuids null or Only one",
        "->isOurProduct(Landroid/bluetooth/BluetoothDevice;)Z",
        "->isWifiSpeaker(Landroid/bluetooth/BluetoothDevice;)Z",
    ]
    if not all(token in original for token in required):
        sys.exit("Beta patch #3 guard failed: isOurSppProduct does not match Libratone 8.3.1.")

    replacement = f'''{header}
    .locals 1

    # ChromeOS/ARC beta patch #3:
    # ARC may expose an incomplete SDP UUID list. Devices already recognized
    # by Libratone's own product check should not fail only because of UUID count.
    if-eqz p1, :cond_false

    invoke-virtual {{p0, p1}}, Lcom/libratone/v3/luci/BlueToothUtil;->isOurProduct(Landroid/bluetooth/BluetoothDevice;)Z
    move-result v0
    if-eqz v0, :cond_false

    invoke-direct {{p0, p1}}, Lcom/libratone/v3/luci/BlueToothUtil;->isWifiSpeaker(Landroid/bluetooth/BluetoothDevice;)Z
    move-result v0
    if-nez v0, :cond_false

    const/4 v0, 0x1
    return v0

    :cond_false
    const/4 v0, 0x0
    return v0
.end method
'''
    path.write_text(s[:start] + replacement + s[end:])
    print("✓ Beta #3: tolerate incomplete ARC SDP UUID lists")
    print("  ↳ removes the developer-facing 'uuids null or Only one' failure path")


def patch_discovery_bonded_fallback(path: pathlib.Path) -> None:
    s = path.read_text()
    start, end, _ = method_bounds(s, "getBtDevices", "(Z)Ljava/util/List;")
    method = s[start:end]

    field_match = re.search(r"(?m)^\.field[^\n]*\sbtDevices:(L[^\n]+;)$", s)
    if not field_match:
        sys.exit("Beta patch #4 guard failed: btDevices field descriptor not found.")
    field_desc = field_match.group(1)

    locals_match = re.search(r"(?m)^(\s*)\.locals\s+(\d+)\s*$", method)
    if not locals_match:
        sys.exit("Beta patch #4 guard failed: getBtDevices .locals not found.")
    old_locals = int(locals_match.group(2))
    v_set, v_list = old_locals, old_locals + 1

    if field_desc == "Ljava/util/List;":
        remove_call = f"invoke-interface {{v{v_list}, v{v_set}}}, Ljava/util/List;->removeAll(Ljava/util/Collection;)Z"
        add_call = f"invoke-interface {{v{v_list}, v{v_set}}}, Ljava/util/List;->addAll(Ljava/util/Collection;)Z"
    elif field_desc == "Ljava/util/ArrayList;":
        remove_call = f"invoke-virtual {{v{v_list}, v{v_set}}}, Ljava/util/ArrayList;->removeAll(Ljava/util/Collection;)Z"
        add_call = f"invoke-virtual {{v{v_list}, v{v_set}}}, Ljava/util/ArrayList;->addAll(Ljava/util/Collection;)Z"
    else:
        sys.exit(f"Beta patch #4 guard failed: unsupported btDevices field type {field_desc}")

    insertion = f'''

    # ChromeOS/ARC beta patch #4:
    # ACTION_FOUND delivery can be incomplete under ARC. Merge bonded Libratone
    # products into the scan backing list. removeAll/addAll keeps this idempotent.
    invoke-virtual {{p0}}, Lcom/libratone/v3/luci/BlueToothUtil;->getBondedProductsList()Ljava/util/Set;
    move-result-object v{v_set}
    iget-object v{v_list}, p0, Lcom/libratone/v3/luci/BlueToothUtil;->btDevices:{field_desc}
    {remove_call}
    {add_call}
'''

    lm_start = start + locals_match.start()
    lm_end = start + locals_match.end()
    new_locals_line = f"{locals_match.group(1)}.locals {old_locals + 2}"
    path.write_text(s[:lm_start] + new_locals_line + insertion + s[lm_end:])
    print("✓ Beta #4: merge bonded Libratone products into discovery results")


def patch_plus_one_main_thread_sleep(path: pathlib.Path) -> None:
    s = path.read_text()
    start, end, _ = method_bounds(s, "onEventMainThread", "(Lcom/libratone/v3/BTStateEvent;)V")
    method = s[start:end]
    sleep_pattern = re.compile(r"(?m)^(\s*)invoke-static \{[^\n]+\}, Ljava/lang/Thread;->sleep\(J\)V\s*$")
    matches = list(sleep_pattern.finditer(method))
    if len(matches) != 1:
        sys.exit(f"Beta patch #5 guard failed: expected one Thread.sleep, found {len(matches)}.")
    match = matches[0]
    replacement = (
        f"{match.group(1)}# ChromeOS/ARC beta patch #5: don't block EventBus MAIN for 500 ms\n"
        f"{match.group(1)}nop"
    )
    method = method[:match.start()] + replacement + method[match.end():]
    path.write_text(s[:start] + method + s[end:])
    print("✓ Beta #5: removed PLUS 1's 500 ms main-thread sleep")


def main() -> None:
    parser = argparse.ArgumentParser(description="Libratone 8.3.1 ChromeOS/ARC beta patch set.")
    parser.add_argument("input", type=pathlib.Path, help="Path to your Libratone 8.3.1 XAPK/ZIP/base APK")
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    if not source.exists():
        sys.exit(f"Input not found: {source}")

    stable.require_commands(["java", "keytool", "python3", "unzip", "zip", "zipalign", "apksigner"])
    stable.download_apktool()
    shutil.rmtree(stable.WORK, ignore_errors=True)
    stable.WORK.mkdir(parents=True)

    input_dir = stable.extract_input(source)
    base = input_dir / "com.libratone.apk"
    stable.verify_version(base)
    decoded = stable.decode(base)
    stable.verify_decoded_metadata(decoded)

    lbt = stable.find_unique(decoded, "LbtBTUtil.smali")
    bt = stable.find_unique(decoded, "BlueToothUtil.smali")
    plus_one = stable.find_unique(decoded, "BTSelectSlaveFragment.smali")

    # Stable compatibility layer: bonded-as-connected + classic manager fallback.
    stable.patch_lbtbtutil(lbt)
    stable.patch_bluetoothutil(bt)

    # Beta UX/robustness layer.
    patch_spp_uuid_gate(bt)
    patch_discovery_bonded_fallback(bt)
    patch_plus_one_main_thread_sleep(plus_one)

    for backup in decoded.rglob("*.smali.bak"):
        backup.unlink()

    patched_dex = stable.rebuild_dex(decoded)
    stable.ensure_keystore()
    stable.package(input_dir, patched_dex)

    print("\nDone (beta patch set).")
    print(f"Patched APKs: {stable.OUTPUT}")
    print("Next: ./install.sh")


if __name__ == "__main__":
    main()
