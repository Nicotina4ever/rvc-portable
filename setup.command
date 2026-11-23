#!/usr/bin/env bash
# RVC Portable - setup macOS (doppio clic da Finder).
set -euo pipefail
cd "$(dirname "$0")"

./setup.sh "$@"
STATUS=$?

if [ -t 0 ]; then
    read -r -p "Premi Invio per chiudere..." _ || true
fi
exit $STATUS
