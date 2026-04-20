#!/usr/bin/env sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LAUNCHER="$SCRIPT_DIR/start-web.py"

if [ -z "${HOST:-}" ]; then
    HOST="0.0.0.0"
    export HOST
fi

if [ "$#" -eq 0 ]; then
    set -- run
fi

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$LAUNCHER" "$@"
fi

if command -v python >/dev/null 2>&1; then
    exec python "$LAUNCHER" "$@"
fi

echo "Python 3 was not found. Install Python first." >&2
exit 1
