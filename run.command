#!/bin/bash
# RVC Portable - doppio click su macOS: apre il Terminale e avvia l'app.
cd "$(dirname "$0")" || exit 1
exec ./run.sh "$@"
