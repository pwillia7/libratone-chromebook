#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$ROOT/output"
TARGET="${ADB_TARGET:-arc:5555}"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb is required." >&2
  exit 1
fi

if [[ ! -d "$OUT" ]] || ! compgen -G "$OUT/*.apk" >/dev/null; then
  echo "No patched APKs found in $OUT. Run ./patch.sh first." >&2
  exit 1
fi

if ! adb devices | awk 'NR>1 {print $1}' | grep -Fxq "$TARGET"; then
  echo "ADB target '$TARGET' is not connected." >&2
  echo "Current devices:" >&2
  adb devices >&2
  exit 1
fi

echo "Installing patched Libratone to $TARGET..."
set +e
adb -s "$TARGET" install-multiple -r "$OUT"/*.apk
status=$?
set -e

if [[ $status -eq 0 ]]; then
  echo "Success."
  exit 0
fi

cat >&2 <<'MSG'

The in-place install failed.

If the currently installed Libratone app is signed by Libratone rather than this
patcher's local key, Android cannot replace it in place. Uninstalling clears the
app's local data.

If you want to continue, run:

  adb -s arc:5555 uninstall com.libratone
  ./install.sh

MSG
exit "$status"
