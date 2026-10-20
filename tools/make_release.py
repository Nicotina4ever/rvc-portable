"""Crea gli archivi di distribuzione per sistema operativo.

    python tools/make_release.py --list
    python tools/make_release.py --target windows
    python tools/make_release.py --target windows --with-runtime
    python tools/make_release.py --target macos --target linux

Gli archivi includono applicazione, UI, cataloghi, docs e launcher.
Modelli, dati utente, quarantena e runtime non vengono inclusi salvo --with-runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tarfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import __version__  # noqa: E402

APP_INCLUDE = [
    "app",
    "web",
    "locales",
    "requirements",
    "docs",
    "tools",
    "launch.py",
    "install.conf",
    "run.bat",
    "run-console.bat",
    "run.sh",
    "run.command",
    "setup.bat",
    "setup.sh",
    "README.md",
    "CHANGELOG.md",
    "pyproject.toml",
    ".gitattributes",
]
EXCLUDE_PARTS = {
    "__pycache__",
    ".pyc",
    ".log",
    ".tmp",
    ".bak",
    ".DS_Store",
    "Thumbs.db",
    "archive",
}
EXCLUDE_DIRS = {"tests", ".dev", ".github", "da_eliminare", "data", "Modelli", "Progetto"}


def _iter_files(base: str, extra_excludes=()):
    for name in os.listdir(base):
        if name in EXCLUDE_DIRS or name in extra_excludes:
            continue
        path = os.path.join(base, name)
        if os.path.isdir(path):
            for sub in _iter_files(path, extra_excludes):
                yield sub
        elif os.path.isfile(path):
            yield path


def _gather(with_runtime: bool) -> list:
    files = []
    for entry in APP_INCLUDE:
        path = os.path.join(ROOT, entry)
        if not os.path.exists(path):
            continue
        if os.path.isdir(path):
            for file_path in _iter_files(path):
                rel = os.path.relpath(file_path, ROOT)
                if any(part in rel.replace("\\", "/").split("/") for part in EXCLUDE_PARTS):
                    continue
                files.append(file_path)
        else:
            files.append(path)
    if with_runtime:
        runtime = os.path.join(ROOT, "runtime")
        if not os.path.isdir(runtime):
            raise SystemExit("runtime/ assente: impossibile creare il pacchetto completo")
        for base, dirs, names in os.walk(runtime):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in names:
                if name.endswith((".pyc", ".pyo")):
                    continue
                files.append(os.path.join(base, name))
    return files


def _archive_prefix(destination: str) -> str:
    """Cartella radice dentro l'archivio, cosi' l'estrazione non sparpaglia i file."""
    name = os.path.basename(destination)
    for suffix in (".zip", ".tar.gz"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return os.path.splitext(name)[0]


def _zip(files, destination: str, compress_runtime: bool) -> None:
    prefix = _archive_prefix(destination)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in files:
            arcname = os.path.join(prefix, os.path.relpath(path, ROOT))
            archive.write(path, arcname)
    _report(destination)


def _targz(files, destination: str) -> None:
    prefix = _archive_prefix(destination)
    with tarfile.open(destination, "w:gz", compresslevel=6) as archive:
        for path in files:
            archive.add(path, arcname=os.path.join(prefix, os.path.relpath(path, ROOT)))
    _report(destination)


def _report(destination: str) -> None:
    size = os.path.getsize(destination)
    digest = hashlib.sha256()
    with open(destination, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    print(
        "creato %s (%.1f MB) sha256=%s"
        % (os.path.basename(destination), size / 1024 / 1024, digest.hexdigest())
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crea archivi di distribuzione")
    parser.add_argument("--target", action="append", choices=("windows", "macos", "linux"))
    parser.add_argument("--output", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--with-runtime", action="store_true", help="include runtime/ (solo Windows)")
    parser.add_argument("--list", action="store_true", help="elenca i file che sarebbero inclusi")
    args = parser.parse_args(argv)

    targets = args.target or ["windows"]
    files = _gather(with_runtime=args.with_runtime and "windows" in targets)
    if args.list:
        for path in sorted(files):
            print(os.path.relpath(path, ROOT))
        print("\n%d file" % len(files))
        return 0

    os.makedirs(args.output, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    for target in targets:
        if target == "windows":
            name = "RVC-Portable-%s-windows-x64.zip" % __version__
            _zip(files, os.path.join(args.output, name), args.with_runtime)
        elif target == "macos":
            name = "RVC-Portable-%s-macos.tar.gz" % __version__
            _targz(files, os.path.join(args.output, name))
        else:
            name = "RVC-Portable-%s-linux-x86_64.tar.gz" % __version__
            _targz(files, os.path.join(args.output, name))
    # SHA256SUMS
    sums = os.path.join(args.output, "SHA256SUMS")
    with open(sums, "w", encoding="utf-8") as handle:
        for name in sorted(os.listdir(args.output)):
            path = os.path.join(args.output, name)
            if not os.path.isfile(path) or name == "SHA256SUMS":
                continue
            digest = hashlib.sha256()
            with open(path, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            handle.write("%s  %s\n" % (digest.hexdigest(), name))
    print("SHA256SUMS aggiornato (%s)" % stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
