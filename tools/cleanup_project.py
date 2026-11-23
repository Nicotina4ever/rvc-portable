"""Pulizia controllata del progetto: sposta gli artefatti non più necessari in da_eliminare/.

Uso:
    python tools/cleanup_project.py --dry-run     # mostra cosa sposterebbe (default)
    python tools/cleanup_project.py --apply       # sposta davvero
    python tools/cleanup_project.py --report      # solo spazio occupato

Non tocca mai Modelli/, Progetto/, runtime/, Reaper/portable/ e data/state/.
La cartella da_eliminare/ è in .gitignore: puoi svuotarla quando vuoi.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUARANTINE = os.path.join(ROOT, "da_eliminare")

# Percorsi generati da test, cache o build locali: rigenerabili, non servono al repo.
CANDIDATES = [
    ("test-artifacts", "data/training/_smoke"),
    ("test-artifacts", "data/training/_apitest"),
    ("test-artifacts", "data/training/jobs"),
    ("test-artifacts", "data/cache"),
    ("browser-profile", "data/browser"),
    ("dist-old", "dist/RVC-Portable-3.0.0-linux-x86_64.tar.gz"),
    ("dist-old", "dist/RVC-Portable-3.0.0-macos.tar.gz"),
    ("dist-old", "dist/RVC-Portable-3.0.0-windows-x64.zip"),
    # Il runtime Windows 3.0.0 e' pubblicato su GitHub (release runtime-v3.0.0):
    # tenerlo qui occupa ~3,6 GB inutili.
    ("dist-runtime", "dist/RVC-Portable-runtime-windows-py39-cu118.zip.001"),
    ("dist-runtime", "dist/RVC-Portable-runtime-windows-py39-cu118.zip.002"),
    ("caches", ".pytest_cache"),
    ("caches", ".ruff_cache"),
]

PROTECTED = [
    "Modelli",
    "Progetto",
    "runtime",
    "Reaper/portable",
    "data/state",
    "app",
    "web",
    "tools",
    "tests",
    "docs",
]


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for base, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%.1f GB" % value


def _is_protected(relative: str) -> bool:
    relative = relative.replace("\\", "/")
    for entry in PROTECTED:
        if relative == entry or relative.startswith(entry + "/"):
            return True
    return False


def _destination(category: str, relative: str) -> str:
    name = os.path.basename(relative.rstrip("/\\"))
    target_dir = os.path.join(QUARANTINE, category)
    target = os.path.join(target_dir, name)
    if os.path.exists(target):
        target = os.path.join(target_dir, "%s-%s" % (name, time.strftime("%Y%m%d-%H%M%S")))
    return target


def scan() -> list:
    items = []
    for category, relative in CANDIDATES:
        path = os.path.join(ROOT, relative)
        if not os.path.exists(path):
            continue
        if _is_protected(relative):
            continue
        items.append((category, relative, path, _size(path)))
    return items


def report() -> None:
    print("Spazio per cartella (solo quelle pesanti):")
    for name in ("runtime", "Modelli", "dist", "data", "Reaper", "da_eliminare", ".dev"):
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            print("  %-14s %s" % (name, _human(_size(path))))
    print("\nQuarantena: %s" % _human(_size(QUARANTINE)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pulizia controllata del progetto")
    parser.add_argument("--apply", action="store_true", help="sposta davvero in da_eliminare/")
    parser.add_argument("--dry-run", action="store_true", help="mostra solo il piano (default)")
    parser.add_argument("--report", action="store_true", help="solo report dello spazio")
    args = parser.parse_args(argv)

    if args.report:
        report()
        return 0

    items = scan()
    if not items:
        print("Niente da spostare: progetto gia' pulito.")
        report()
        return 0

    total = sum(item[3] for item in items)
    print("Piano di pulizia (%s da spostare in da_eliminare/):" % _human(total))
    for category, relative, _path, size in items:
        print("  %-16s %-58s %s" % (category, relative, _human(size)))

    if not args.apply:
        print("\nDry-run: usa --apply per eseguire.")
        return 0

    os.makedirs(QUARANTINE, exist_ok=True)
    moved = 0
    for category, relative, path, _size_value in items:
        target = _destination(category, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            shutil.move(path, target)
            moved += 1
            print("spostato: %s -> %s" % (relative, os.path.relpath(target, ROOT)))
        except OSError as exc:
            print("ERRORE su %s: %s" % (relative, exc))

    print("\nSpostati %d elementi. Quarantena: %s" % (moved, _human(_size(QUARANTINE))))
    print("Quando sei sicuro puoi svuotare da_eliminare/ (non e' versionata).")
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
