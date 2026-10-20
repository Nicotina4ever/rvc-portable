#!/usr/bin/env bash
# RVC Portable - launcher Linux/macOS.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in "./runtime/bin/python3" "./.venv/bin/python3"; do
    if [ -x "$candidate" ]; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Runtime non installato: esegui prima ./setup.sh" >&2
    echo "  ./setup.sh                 # macOS / Linux (python3.10+)" >&2
    echo "  ./setup.sh --profile cpu   # senza GPU" >&2
    exit 1
fi

exec "$PY" launch.py "$@"
