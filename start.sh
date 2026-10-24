#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Prefer system Python for the native Quickshell backend and desktop fallbacks.
if [[ -x /usr/bin/python3 ]]; then
    exec /usr/bin/python3 -m dota_background "$@"
fi
exec python3 -m dota_background "$@"
