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


def patch_lbtbtutil(path: pathlib.Path) -> None:
    s = path.read_text()
    method = ".method private static final getConnectedBtDeviceList$getConnected"
    if method not in s:
        sys.exit("Patch 1 guard failed: target method not found.")

    method_pos = s.index(method)
    start = s.find("    :try_start_0\n", method_pos)
    end_marker = "    :try_end_0\n"
    end = s.find(end_marker, start)
    if start < 0 or end < 0:
        sys.exit("Patch 1 guard failed: expected try block not found.")
    end += len(end_marker)

    original = s[start:end]
    required = [
        'const-string v3, "isConnected"',
        'Ljava/lang/reflect/Method;->invoke',
        'Ljava/lang/Boolean;->booleanValue()Z',
    ]
    if not all(token in original for token in required):
        sys.exit("Patch 1 guard failed: method body does not match Libratone 8.3.1 layout.")

    replacement = '''    :try_start_0
    # ChromeOS/ARC compatibility patch #1:
    # ARC may expose ChromeOS-connected Libratone devices as bonded while
    # BluetoothDevice.isConnected() remains false. Libratone products use
    # the C4:67:B5 OUI in this app's own isOurProduct() check.
    invoke-virtual {v1}, Landroid/bluetooth/BluetoothDevice;->getAddress()Ljava/lang/String;
    move-result-object v2
    invoke-virtual {v2}, Ljava/lang/String;->toUpperCase()Ljava/lang/String;
    move-result-object v2
    const-string v3, "C4:67:B5"
    invoke-virtual {v2, v3}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :cond_0
    invoke-static {v1}, Lkotlin/jvm/internal/Intrinsics;->checkNotNull(Ljava/lang/Object;)V
    invoke-interface {v0, v1}, Ljava/util/List;->add(Ljava/lang/Object;)Z
    :try_end_0
'''
    path.write_text(s[:start] + replacement + s[end:])
    print("✓ Applied patch #1 (bonded Libratone devices count as connected candidates)")


def patch_bluetoothutil(path: pathlib.Path) -> None:
    s = path.read_text()
    marker = '''    .line 255
    :cond_0
    iget-boolean p2, p0, Lcom/libratone/v3/luci/BlueToothUtil;->mIsBTConnectReveiverRegistered:Z
'''
    if marker not in s:
        sys.exit("Patch 2 guard failed: registerBTClassicReceiver insertion point not found.")

    replacement = '''    .line 255
    :cond_0

    # ChromeOS/ARC compatibility patch #2:
    # ARC may not emit the Android A2DP CONNECTION_STATE_CHANGED broadcast
    # Libratone expects. Seed the app's classic-connected manager from bonded
    # Libratone products whenever this receiver path is initialized.
    invoke-virtual {p0}, Lcom/libratone/v3/luci/BlueToothUtil;->getBondedProductsList()Ljava/util/Set;
    move-result-object v1
    iget-object v2, p0, Lcom/libratone/v3/luci/BlueToothUtil;->lbtBTClassicConnectedManager:Lcom/libratone/v3/luci/BlueToothUtil$LbtBTClassicConnectedManager;
    invoke-virtual {v2, v1}, Lcom/libratone/v3/luci/BlueToothUtil$LbtBTClassicConnectedManager;->add(Ljava/util/Set;)V

    iget-boolean p2, p0, Lcom/libratone/v3/luci/BlueToothUtil;->mIsBTConnectReveiverRegistered:Z
'''
    path.write_text(s.replace(marker, replacement, 1))
    print("✓ Applied patch #2 (seed classic-connected manager from bonded products)")


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
    patch_lbtbtutil(lbt)
    patch_bluetoothutil(bt)

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
