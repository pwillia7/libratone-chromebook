#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/Libratone_v8.3.1.xapk" >&2
  exit 2
fi

exec python3 "$ROOT/patcher.py" "$1"
