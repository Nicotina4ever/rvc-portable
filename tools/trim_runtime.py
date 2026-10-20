"""Sfoltisce il runtime Windows spostando (mai cancellando) i pacchetti inutilizzati.

I pacchetti vengono spostati in ``da_eliminare/runtime-package-trim/`` e possono
essere ripristinati con ``--restore``. Dopo lo spostamento viene verificato che
motore e torch continuino a importarsi.

    python tools/trim_runtime.py             # dry-run
    python tools/trim_runtime.py --apply
    python tools/trim_runtime.py --restore
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = os.name == "nt"
RUNTIME = os.path.join(ROOT, "runtime")
SITE_PACKAGES = os.path.join(RUNTIME, "Lib", "site-packages") if IS_WINDOWS else os.path.join(
    RUNTIME, "lib", "python3.10", "site-packages"
)
TRIM_DIR = os.path.join(ROOT, "da_eliminare", "runtime-package-trim")
MANIFEST = os.path.join(TRIM_DIR, "manifest.json")

# Pacchetti non usati dall'app 3.0 (motore torch + API + UI).
# Ogni voce: (nome cartella pacchetto, glob dei dist-info).
CANDIDATES = [
    ("gradio", ["gradio-*.dist-info"]),
    ("tensorboard", ["tensorboard-*.dist-info"]),
    ("tensorboard_plugin_wit", ["tensorboard_plugin_wit-*.dist-info"]),
    ("tensorboard_data_server", ["tensorboard_data_server-*.dist-info"]),
    ("onnx", ["onnx-*.dist-info"]),
    ("onnxruntime", ["onnxruntime-*.dist-info"]),
    ("onnxconverter_common", ["onnxconverter_common-*.dist-info"]),
    ("skl2onnx", ["skl2onnx-*.dist-info"]),
    ("torch_directml", ["torch_directml-*.dist-info", "torch-directml-*.dist-info"]),
    ("onnxruntime-dml", []),
]


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def _targets():
    entries = []
    for package, patterns in CANDIDATES:
        path = os.path.join(SITE_PACKAGES, package)
        if not os.path.exists(path):
            continue
        entries.append({"kind": "package", "name": package, "path": path})
        for pattern in patterns:
            for match in glob.glob(os.path.join(SITE_PACKAGES, pattern)):
                entries.append({"kind": "dist-info", "name": os.path.basename(match), "path": match})
    return entries


def _runtime_python() -> str:
    return os.path.join(RUNTIME, "python.exe" if IS_WINDOWS else "bin/python3")


def _verify() -> bool:
    python = _runtime_python()
    if not os.path.isfile(python):
        print("runtime non trovato: verifica saltata")
        return True
    code = "import torch, rvc_python.infer, fastapi, soundfile; print('IMPORT OK')"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    completed = subprocess.run(
        [python, "-B", "-c", code], capture_output=True, text=True, cwd=ROOT, env=env
    )
    ok = completed.returncode == 0 and "IMPORT OK" in (completed.stdout or "")
    print("verifica import: %s" % ("OK" if ok else "FALLITA"))
    if not ok:
        print((completed.stderr or completed.stdout or "")[-800:])
    return ok


def plan() -> None:
    total = 0
    for entry in _targets():
        size = _size(entry["path"])
        total += size
        print("%-12s %-42s %8.1f MB" % (entry["kind"], entry["name"], size / 1024 / 1024))
    print("\nTotale recuperabile: %.1f MB" % (total / 1024 / 1024))


def apply() -> int:
    entries = _targets()
    if not entries:
        print("Nessun pacchetto da sfoltire.")
        return 0
    os.makedirs(TRIM_DIR, exist_ok=True)
    moved = []
    total = 0
    for entry in entries:
        size = _size(entry["path"])
        destination = os.path.join(TRIM_DIR, os.path.basename(entry["path"]))
        if os.path.exists(destination):
            print("gia' in quarantena: %s" % entry["name"])
            continue
        shutil.move(entry["path"], destination)
        moved.append({"name": entry["name"], "kind": entry["kind"], "bytes": size,
                      "destination": os.path.relpath(destination, ROOT)})
        total += size
        print("spostato: %s (%.1f MB)" % (entry["name"], size / 1024 / 1024))
    manifest = {}
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, ValueError):
            manifest = {}
    manifest.setdefault("entries", []).extend(moved)
    manifest["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    print("\nSpostati %.1f MB in %s" % (total / 1024 / 1024, os.path.relpath(TRIM_DIR, ROOT)))
    ok = _verify()
    if not ok:
        print("ATTENZIONE: la verifica import e' fallita; ripristina con --restore")
        return 1
    print("Runtime sfoltito e verificato. Suggerito: eseguire anche tests\\e2e\\run_real_conversion.py")
    return 0


def restore() -> int:
    if not os.path.isfile(MANIFEST):
        print("manifest di trim assente")
        return 2
    with open(MANIFEST, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    restored = 0
    for entry in reversed(manifest.get("entries", [])):
        source = os.path.join(ROOT, entry["destination"])
        destination = os.path.join(SITE_PACKAGES, entry["name"])
        if not os.path.exists(source):
            continue
        if os.path.exists(destination):
            print("destinazione gia' presente: %s" % entry["name"])
            continue
        shutil.move(source, destination)
        restored += 1
        print("ripristinato: %s" % entry["name"])
    print("Ripristinati %d elementi." % restored)
    _verify()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sfoltisce il runtime (sposta, non cancella)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args(argv)
    if args.restore:
        return restore()
    if args.apply:
        return apply()
    plan()
    print("\nDry-run: usa --apply per spostare, --restore per tornare indietro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
