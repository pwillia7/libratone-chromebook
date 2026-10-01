#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

PACKAGE = "com.libratone"
EXPECTED_VERSION_NAME = "8.3.1"
EXPECTED_VERSION_CODE = "831"
APKTOOL_VERSION = "3.0.2"
APKTOOL_URL = f"https://github.com/iBotPeaches/Apktool/releases/download/v{APKTOOL_VERSION}/apktool_{APKTOOL_VERSION}.jar"

ROOT = pathlib.Path(__file__).resolve().parent
WORK = ROOT / ".work"
OUTPUT = ROOT / "output"
TOOLS = ROOT / ".tools"
APKTOOL = TOOLS / f"apktool_{APKTOOL_VERSION}.jar"

KEYSTORE = pathlib.Path.home() / ".local/share/libratone-chromebook/signing.keystore"
KEY_ALIAS = "libratone-patch"
KEY_PASSWORD = "libratone-chromebook"


def run(*args: str, cwd: pathlib.Path | None = None, check: bool = True, capture: bool = False):
    print("+", " ".join(map(str, args)))
    return subprocess.run(
        list(map(str, args)),
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def require_commands(names: list[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        sys.exit("Missing required commands: " + ", ".join(missing))


def download_apktool() -> None:
    if APKTOOL.exists():
        return
    TOOLS.mkdir(parents=True, exist_ok=True)
    if shutil.which("wget"):
        run("wget", "-O", APKTOOL, APKTOOL_URL)
    elif shutil.which("curl"):
        run("curl", "-L", "-o", APKTOOL, APKTOOL_URL)
    else:
        sys.exit("Need wget or curl to download Apktool.")


def extract_input(source: pathlib.Path) -> pathlib.Path:
    extract_dir = WORK / "input"
    shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True)

    if source.suffix.lower() in {".xapk", ".zip"}:
        with zipfile.ZipFile(source) as zf:
            zf.extractall(extract_dir)
    elif source.suffix.lower() == ".apk":
        # A standalone base APK is accepted for patch development, but split install
        # support requires the original XAPK split APKs.
        shutil.copy2(source, extract_dir / "com.libratone.apk")
    else:
        sys.exit("Input must be a .xapk, .zip, or .apk file.")

    base = extract_dir / "com.libratone.apk"
    if not base.exists():
        apks = sorted(extract_dir.glob("*.apk"))
        candidates = [p for p in apks if not p.name.startswith("config.")]
        if len(candidates) == 1:
            candidates[0].rename(base)
        else:
            sys.exit("Could not identify Libratone base APK in the supplied archive.")
    return extract_dir


def verify_version(base: pathlib.Path) -> None:
    # Prefer aapt/aapt2 if present. The structural patch guards below remain the
    # ultimate safety check if metadata tooling is unavailable.
    tool = shutil.which("aapt2") or shutil.which("aapt")
    if not tool:
        print("! aapt/aapt2 not found; skipping manifest version precheck.")
        return

    proc = run(tool, "dump", "badging", base, capture=True, check=False)
    out = proc.stdout or ""
    m = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", out)
    if not m:
        print("! Could not parse APK badging; continuing with structural guards.")
        return
    package, version_code, version_name = m.groups()
    if package != PACKAGE or version_code != EXPECTED_VERSION_CODE or version_name != EXPECTED_VERSION_NAME:
        sys.exit(
            f"Unsupported APK: package={package} versionCode={version_code} versionName={version_name}. "
            f"Expected {PACKAGE} {EXPECTED_VERSION_NAME} ({EXPECTED_VERSION_CODE})."
        )
    print(f"✓ Verified {package} {version_name} ({version_code})")


def decode(base: pathlib.Path) -> pathlib.Path:
    decoded = WORK / "decoded"
    shutil.rmtree(decoded, ignore_errors=True)
    run("java", "-jar", APKTOOL, "d", "-f", base, "-o", decoded)
    return decoded


def verify_decoded_metadata(decoded: pathlib.Path) -> None:
    manifest = (decoded / "AndroidManifest.xml").read_text(errors="replace")
    if f'package="{PACKAGE}"' not in manifest:
        sys.exit(f"Unsupported package: decoded manifest is not {PACKAGE}.")

    yml = (decoded / "apktool.yml").read_text(errors="replace")
    version_code_ok = re.search(r"versionCode:\s*['\"]?831['\"]?", yml) is not None
    version_name_ok = re.search(r"versionName:\s*['\"]?8\.3\.1['\"]?", yml) is not None
    if not (version_code_ok and version_name_ok):
        sys.exit(
            "Unsupported Libratone build: decoded metadata does not match "
            f"{EXPECTED_VERSION_NAME} ({EXPECTED_VERSION_CODE})."
        )
    print(f"✓ Decoded metadata matches {EXPECTED_VERSION_NAME} ({EXPECTED_VERSION_CODE})")


def find_unique(root: pathlib.Path, name: str) -> pathlib.Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        sys.exit(f"Expected exactly one {name}, found {len(matches)}: {matches}")
    return matches[0]


def verify_lbtbtutil(path: pathlib.Path) -> None:
    # Earlier versions of this patcher replaced LbtBTUtil's
    # BluetoothDevice.isConnected() check with "MAC starts with C4:67:B5".
    # That made every bonded Libratone speaker look connected and was removed:
    # ARC mirrors ChromeOS's physical link state into isConnected(), so the
    # app's original check is correct. We only verify the expected layout here.
    s = path.read_text()
    method = ".method private static final getConnectedBtDeviceList$getConnected"
    if method not in s:
        sys.exit("LbtBTUtil guard failed: target method not found.")
    body = s[s.index(method):]
    body = body[: body.index(".end method")]
    required = [
        'const-string v3, "isConnected"',
        "Ljava/lang/reflect/Method;->invoke",
        "Ljava/lang/Boolean;->booleanValue()Z",
    ]
    if not all(token in body for token in required):
        sys.exit("LbtBTUtil guard failed: method body does not match Libratone 8.3.1 layout.")
    print("✓ LbtBTUtil left unmodified (original isConnected() check works under ARC)")


ARC_SYNC_METHOD = """# ChromeOS/ARC compatibility patch (arcSyncConnectedProducts):
# Add bonded Libratone products that ARC reports as physically connected
# (BluetoothDevice.isConnected(), mirrored from ChromeOS) and drop entries that
# are no longer connected, so SPP auto-connect targets the speaker ChromeOS is
# actually using instead of whichever bonded speaker the map yields first.
.method public arcSyncConnectedProducts()V
    .locals 9

    invoke-virtual {p0}, Lcom/libratone/v3/luci/BlueToothUtil;->getBondedProductsList()Ljava/util/Set;

    move-result-object v0

    iget-object v1, p0, Lcom/libratone/v3/luci/BlueToothUtil;->lbtBTClassicConnectedManager:Lcom/libratone/v3/luci/BlueToothUtil$LbtBTClassicConnectedManager;

    # v2 = addresses of bonded products that are physically connected
    new-instance v2, Ljava/util/HashSet;

    invoke-direct {v2}, Ljava/util/HashSet;-><init>()V

    iget-object v8, v1, Lcom/libratone/v3/luci/BlueToothUtil$LbtBTClassicConnectedManager;->mListLbtBTClassicConnected:Ljava/util/concurrent/ConcurrentHashMap;

    invoke-interface {v0}, Ljava/util/Set;->iterator()Ljava/util/Iterator;

    move-result-object v0

    :goto_add
    invoke-interface {v0}, Ljava/util/Iterator;->hasNext()Z

    move-result v3

    if-eqz v3, :cond_add_done

    invoke-interface {v0}, Ljava/util/Iterator;->next()Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Landroid/bluetooth/BluetoothDevice;

    invoke-virtual {v3}, Landroid/bluetooth/BluetoothDevice;->getAddress()Ljava/lang/String;

    move-result-object v4

    if-eqz v4, :goto_add

    invoke-static {v3}, Lcom/libratone/v3/luci/ArcBtCompat;->isConnected(Landroid/bluetooth/BluetoothDevice;)Z

    move-result v5

    sget-object v6, Lcom/libratone/v3/luci/BlueToothUtil;->TAG:Ljava/lang/String;

    new-instance v7, Ljava/lang/StringBuilder;

    const-string p0, "arcSync "

    invoke-direct {v7, p0}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V

    invoke-virtual {v7, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const-string p0, " connected="

    invoke-virtual {v7, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v7, v5}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;

    invoke-virtual {v7}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v7

    invoke-static {v6, v7}, Lcom/libratone/v3/util/GTLog;->d(Ljava/lang/String;Ljava/lang/String;)V

    if-eqz v5, :goto_add

    invoke-interface {v2, v4}, Ljava/util/Set;->add(Ljava/lang/Object;)Z

    # manager.add() ignores already-present keys and triggers SPP selection for new ones
    invoke-virtual {v1, v4, v3}, Lcom/libratone/v3/luci/BlueToothUtil$LbtBTClassicConnectedManager;->add(Ljava/lang/String;Landroid/bluetooth/BluetoothDevice;)V

    goto :goto_add

    :cond_add_done
    # drop entries that are no longer connected (or no longer bonded)
    new-instance v0, Ljava/util/ArrayList;

    invoke-virtual {v8}, Ljava/util/concurrent/ConcurrentHashMap;->keySet()Ljava/util/concurrent/ConcurrentHashMap$KeySetView;

    move-result-object v3

    invoke-direct {v0, v3}, Ljava/util/ArrayList;-><init>(Ljava/util/Collection;)V

    invoke-virtual {v0}, Ljava/util/ArrayList;->iterator()Ljava/util/Iterator;

    move-result-object v0

    :goto_del
    invoke-interface {v0}, Ljava/util/Iterator;->hasNext()Z

    move-result v3

    if-eqz v3, :cond_del_done

    invoke-interface {v0}, Ljava/util/Iterator;->next()Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Ljava/lang/String;

    invoke-interface {v2, v3}, Ljava/util/Set;->contains(Ljava/lang/Object;)Z

    move-result v4

    if-nez v4, :goto_del

    invoke-virtual {v1, v3}, Lcom/libratone/v3/luci/BlueToothUtil$LbtBTClassicConnectedManager;->del(Ljava/lang/String;)V

    goto :goto_del

    :cond_del_done
    invoke-static {}, Lcom/libratone/v3/luci/ArcBtCompat;->ensureAclReceiver()V

    return-void
.end method

"""


def patch_bluetoothutil(path: pathlib.Path) -> None:
    s = path.read_text()
    marker = """    .line 255
    :cond_0
    iget-boolean p2, p0, Lcom/libratone/v3/luci/BlueToothUtil;->mIsBTConnectReveiverRegistered:Z
"""
    if marker not in s:
        sys.exit("Patch guard failed: registerBTClassicReceiver insertion point not found.")
    method_sig = ".method public registerBTClassicReceiver(Landroid/content/Context;Z)V"
    if s.count(method_sig) != 1:
        sys.exit("Patch guard failed: registerBTClassicReceiver signature not found exactly once.")
    if "arcSyncConnectedProducts" in s:
        sys.exit("Patch guard failed: BlueToothUtil already contains arcSyncConnectedProducts.")
    required = [
        ".field private static final TAG:Ljava/lang/String;",
        ".field private final lbtBTClassicConnectedManager:Lcom/libratone/v3/luci/BlueToothUtil$LbtBTClassicConnectedManager;",
        ".method public getBondedProductsList()Ljava/util/Set;",
    ]
    missing = [token for token in required if token not in s]
    if missing:
        sys.exit(f"Patch guard failed: BlueToothUtil is missing {missing}.")

    replacement = """    .line 255
    :cond_0

    # ChromeOS/ARC compatibility patch:
    # ARC doesn't emit the A2DP CONNECTION_STATE_CHANGED broadcast Libratone
    # expects, so sync the classic-connected manager with the bonded Libratone
    # products that are actually connected (not every bonded product).
    invoke-virtual {p0}, Lcom/libratone/v3/luci/BlueToothUtil;->arcSyncConnectedProducts()V

    iget-boolean p2, p0, Lcom/libratone/v3/luci/BlueToothUtil;->mIsBTConnectReveiverRegistered:Z
"""
    s = s.replace(marker, replacement, 1)
    s = s.replace(method_sig, ARC_SYNC_METHOD + method_sig, 1)
    path.write_text(s)
    print("✓ Patched BlueToothUtil (sync classic-connected manager with ARC-connected products)")


def verify_connected_manager(path: pathlib.Path) -> None:
    s = path.read_text()
    required = [
        ".field mListLbtBTClassicConnected:Ljava/util/concurrent/ConcurrentHashMap;",
        ".method declared-synchronized add(Ljava/lang/String;Landroid/bluetooth/BluetoothDevice;)V",
        ".method declared-synchronized del(Ljava/lang/String;)V",
    ]
    missing = [token for token in required if token not in s]
    if missing:
        sys.exit(f"Patch guard failed: LbtBTClassicConnectedManager is missing {missing}.")


def add_arc_compat_class(bluetoothutil: pathlib.Path) -> None:
    src = ROOT / "patches" / "ArcBtCompat.smali"
    dest = bluetoothutil.parent / "ArcBtCompat.smali"
    if dest.exists():
        sys.exit(f"Patch guard failed: {dest} already exists in the decoded app.")
    shutil.copy2(src, dest)
    print("✓ Added ArcBtCompat (isConnected() helper + ACL connect/disconnect receiver)")


def rebuild_dex(decoded: pathlib.Path) -> pathlib.Path:
    # The full resource link is expected to fail on this app because decoded
    # resources refer to private framework colors. Apktool smalis dex files first,
    # so we deliberately harvest the rebuilt classes6.dex afterwards.
    throwaway = WORK / "throwaway.apk"
    proc = run("java", "-jar", APKTOOL, "b", decoded, "-o", throwaway, check=False, capture=True)
    print(proc.stdout or "")

    dex = decoded / "build/apk/classes6.dex"
    if not dex.exists():
        sys.exit("Apktool did not produce build/apk/classes6.dex; cannot continue.")
    print("✓ Rebuilt patched classes6.dex")
    return dex


def ensure_keystore() -> None:
    if KEYSTORE.exists():
        print(f"✓ Reusing signing key: {KEYSTORE}")
        return
    KEYSTORE.parent.mkdir(parents=True, exist_ok=True)
    run(
        "keytool", "-genkeypair",
        "-keystore", KEYSTORE,
        "-alias", KEY_ALIAS,
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "10000",
        "-storepass", KEY_PASSWORD,
        "-keypass", KEY_PASSWORD,
        "-dname", "CN=Libratone Chromebook Patch",
    )
    print(f"✓ Created signing key: {KEYSTORE}")


def strip_old_signatures(apk: pathlib.Path) -> None:
    # zip -d returns 12 when no files match; ignore that case.
    run(
        "zip", "-d", apk,
        "META-INF/*.RSA", "META-INF/*.DSA", "META-INF/*.EC",
        "META-INF/*.SF", "META-INF/MANIFEST.MF",
        check=False,
    )


def sign(apk_in: pathlib.Path, apk_out: pathlib.Path) -> None:
    run(
        "apksigner", "sign",
        "--ks", KEYSTORE,
        "--ks-key-alias", KEY_ALIAS,
        "--ks-pass", f"pass:{KEY_PASSWORD}",
        "--key-pass", f"pass:{KEY_PASSWORD}",
        "--out", apk_out,
        apk_in,
    )


def package(input_dir: pathlib.Path, patched_dex: pathlib.Path) -> None:
    shutil.rmtree(OUTPUT, ignore_errors=True)
    OUTPUT.mkdir(parents=True)

    original_base = input_dir / "com.libratone.apk"
    work_base = WORK / "com.libratone.patched-unsigned.apk"
    aligned = WORK / "com.libratone.patched-aligned.apk"
    shutil.copy2(original_base, work_base)

    # Replace only classes6.dex; preserve original resources/assets/native libs.
    run("zip", "-d", work_base, "classes6.dex")
    temp_dex_dir = WORK / "dex"
    shutil.rmtree(temp_dex_dir, ignore_errors=True)
    temp_dex_dir.mkdir(parents=True)
    shutil.copy2(patched_dex, temp_dex_dir / "classes6.dex")
    run("zip", "-q", "-u", work_base, "classes6.dex", cwd=temp_dex_dir)

    strip_old_signatures(work_base)
    run("zipalign", "-f", "-p", "4", work_base, aligned)
    sign(aligned, OUTPUT / "com.libratone.apk")

    splits = sorted(input_dir.glob("config*.apk"))
    if not splits:
        print("! No config split APKs found. Output contains only the patched base APK.")
    for split in splits:
        split_unsigned = WORK / f"{split.stem}.unsigned.apk"
        split_aligned = WORK / f"{split.stem}.aligned.apk"
        shutil.copy2(split, split_unsigned)
        strip_old_signatures(split_unsigned)
        run("zipalign", "-f", "-p", "4", split_unsigned, split_aligned)
        sign(split_aligned, OUTPUT / split.name)

    # Verify all output APKs carry the same certificate.
    fingerprints = set()
    for apk in sorted(OUTPUT.glob("*.apk")):
        proc = run("apksigner", "verify", "--print-certs", apk, capture=True)
        lines = [line for line in (proc.stdout or "").splitlines() if "certificate SHA-256 digest:" in line]
        if not lines:
            sys.exit(f"Could not verify signing certificate for {apk.name}")
        fingerprints.add(lines[0].split(":", 1)[1].strip())
    if len(fingerprints) != 1:
        sys.exit("Signed APK certificate mismatch detected.")
    print("✓ Signed and verified output APK set")


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch Libratone 8.3.1 for ChromeOS/ARC Bluetooth behavior.")
    parser.add_argument("input", type=pathlib.Path, help="Path to your Libratone 8.3.1 XAPK/ZIP/base APK")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    if not source.exists():
        sys.exit(f"Input not found: {source}")

    require_commands(["java", "keytool", "python3", "unzip", "zip", "zipalign", "apksigner"])
    download_apktool()
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)

    input_dir = extract_input(source)
    base = input_dir / "com.libratone.apk"
    verify_version(base)
    decoded = decode(base)
    verify_decoded_metadata(decoded)

    lbt = find_unique(decoded, "LbtBTUtil.smali")
    bt = find_unique(decoded, "BlueToothUtil.smali")
    manager = find_unique(decoded, "BlueToothUtil$LbtBTClassicConnectedManager.smali")
    verify_lbtbtutil(lbt)
    verify_connected_manager(manager)
    patch_bluetoothutil(bt)
    add_arc_compat_class(bt)

    # Avoid Apktool treating local backup files as unknown smali file types.
    for backup in decoded.rglob("*.smali.bak"):
        backup.unlink()

    patched_dex = rebuild_dex(decoded)
    ensure_keystore()
    package(input_dir, patched_dex)

    print("\nDone.")
    print(f"Patched APKs: {OUTPUT}")
    print("Next: ./install.sh")


if __name__ == "__main__":
    main()
