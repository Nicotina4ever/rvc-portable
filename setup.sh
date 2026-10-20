#!/usr/bin/env bash
# RVC Portable - setup/verifica ambiente (Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")"

PY="$(command -v python3.10 || command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "Python 3.10 (o superiore) non trovato: installalo prima di proseguire." >&2
    exit 1
fi

"$PY" tools/bootstrap.py "$@"

if [ -t 0 ]; then
    read -r -p "Premi Invio per chiudere..." _ || true
fi
