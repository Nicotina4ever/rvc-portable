#!/usr/bin/env bash
# RVC Portable - setup/verifica ambiente (Linux/macOS).
#
#   ./setup.sh                  installa (auto: CUDA se disponibile, altrimenti CPU)
#   ./setup.sh --profile cpu    forza CPU
#   ./setup.sh --profile cuda118
#   ./setup.sh --check          solo verifica
set -euo pipefail
cd "$(dirname "$0")"

PY="$(command -v python3.10 || command -v python3.11 || command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "Python 3.10 (o superiore) non trovato: installalo prima di proseguire." >&2
    exit 1
fi

# Se l'utente chiede solo la verifica, non installare nulla.
CHECK_ONLY=0
for arg in "$@"; do
    if [ "$arg" = "--check" ]; then CHECK_ONLY=1; fi
done

if [ "$CHECK_ONLY" -eq 0 ]; then
    "$PY" tools/bootstrap.py --install "$@"
fi
"$PY" tools/bootstrap.py --check

if [ -t 0 ]; then
    read -r -p "Premi Invio per chiudere..." _ || true
fi
