"""Ripristina il runtime Windows Python 3.9 funzionante dall'archivio storico.

L'archivio `Progetto/RVC-PortableConMonitoraggio.zip` contiene la distribuzione
portatile storicamente funzionante (CPython 3.9.13 + torch 2.0.0+cu118 +
rvc-python 0.1.5 + fairseq 0.12.2 + pesi HuBERT/RMVPE). Questo strumento
estrae soltanto `Windows/runtime/**` in una cartella di destinazione, senza
toccare il runtime attuale.

Uso:
    python tools/restore_runtime_windows.py --dry-run
    python tools/restore_runtime_windows.py --dest runtime-py39
    python tools/restore_runtime_windows.py --dest runtime-py39 --force

Note:
- le cartelle `__pycache__` e i file `.pyc` vengono saltati (rigenerati);
- la destinazione deve essere vuota o assente, salvo `--force`;
- al termine viene scritto `.restore-manifest.json` con identità e conteggi.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
import time
import zipfile

DEFAULT_ARCHIVE = os.path.join("Progetto", "RVC-PortableConMonitoraggio.zip")
DEFAULT_PREFIX = "Windows/runtime/"
REQUIRED_FILES = (
    "python.exe",
    "pythonw.exe",
    "python39.dll",
    "python39.zip",
    "Lib/site-packages/rvc_python/__init__.py",
    "Lib/site-packages/fairseq/__init__.py",
    "Lib/site-packages/torch/__init__.py",
    "Lib/site-packages/rvc_python/base_model/hubert_base.pt",
    "Lib/site-packages/rvc_python/base_model/rmvpe.pt",
)


def _sha256_file(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _is_skipped(name: str) -> bool:
    parts = name.split("/")
    if "__pycache__" in parts:
        return True
    return name.endswith((".pyc", ".pyo"))


def _dir_is_empty(path: str) -> bool:
    return not os.path.isdir(path) or not os.listdir(path)


def restore(archive: str, prefix: str, dest: str, force: bool, dry_run: bool) -> int:
    archive = os.path.abspath(archive)
    dest = os.path.abspath(dest)

    if not os.path.isfile(archive):
        print(f"[ERRORE] Archivio non trovato: {archive}")
        return 2

    if not _dir_is_empty(dest) and not force:
        print(f"[ERRORE] Destinazione non vuota: {dest} (usa --force per sovrascrivere)")
        return 3

    print(f"Archivio: {archive}")
    print(f"Prefisso: {prefix}")
    print(f"Destinazione: {dest}")
    if dry_run:
        print("[DRY-RUN] Nessun file verrà scritto.")

    started = time.time()
    extracted = 0
    skipped = 0
    total_bytes = 0
    archive_bytes = os.path.getsize(archive)

    with zipfile.ZipFile(archive) as zf:
        members = [
            info
            for info in zf.infolist()
            if info.filename.startswith(prefix) and not info.is_dir()
        ]
        if not members:
            print(f"[ERRORE] Nessuna voce con prefisso {prefix!r} nell'archivio")
            return 4
        print(f"Voci da estrarre: {len(members)}")

        for idx, info in enumerate(members, start=1):
            rel = info.filename[len(prefix):]
            if not rel or _is_skipped(rel):
                skipped += 1
                continue
            target = os.path.join(dest, rel.replace("/", os.sep))
            total_bytes += info.file_size
            if dry_run:
                extracted += 1
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
            extracted += 1
            if idx % 2000 == 0 or idx == len(members):
                pct = idx * 100.0 / len(members)
                elapsed = time.time() - started
                print(
                    f"  {idx}/{len(members)} ({pct:5.1f}%) "
                    f"{total_bytes / (1024 ** 3):.2f} GB estratti, {elapsed:.0f}s",
                    flush=True,
                )

    if dry_run:
        print(
            f"[DRY-RUN] Estraibili {extracted} file, {skipped} saltati, "
            f"{total_bytes / (1024 ** 3):.2f} GB."
        )
        return 0

    # L'interprete embeddable usa python39._pth e ignora PYTHONPATH: aggiungiamo
    # un .pth in site-packages che punta alla radice del progetto (3 livelli su),
    # cosi' `python -m app`, `launch.py` e i test funzionano da qualunque cwd.
    site_packages = os.path.join(dest, "Lib", "site-packages")
    if os.path.isdir(site_packages):
        pth_path = os.path.join(site_packages, "_rvc_portable_root.pth")
        with open(pth_path, "w", encoding="ascii") as fh:
            fh.write("../../..\n")
        print(f"Creato {pth_path} -> radice progetto")

    missing = [name for name in REQUIRED_FILES if not os.path.isfile(os.path.join(dest, name))]
    manifest = {
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "source_archive": archive,
        "source_archive_sha256": _sha256_file(archive),
        "source_archive_bytes": archive_bytes,
        "prefix": prefix,
        "destination": dest,
        "files_extracted": extracted,
        "files_skipped": skipped,
        "bytes_extracted": total_bytes,
        "elapsed_seconds": round(time.time() - started, 1),
        "required_files_missing": missing,
    }
    with open(os.path.join(dest, ".restore-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"Estratti {extracted} file, saltati {skipped}, {total_bytes / (1024 ** 3):.2f} GB.")
    if missing:
        print("[ATTENZIONE] File obbligatori mancanti:")
        for name in missing:
            print(f"  - {name}")
        return 5

    print("Runtime ripristinato. Prossimo passo: validazione (import + CUDA + conversione).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", default=DEFAULT_ARCHIVE, help="Archivio ZIP storico")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Prefisso interno da estrarre")
    parser.add_argument("--dest", default="runtime-py39", help="Cartella di destinazione")
    parser.add_argument("--force", action="store_true", help="Sovrascrive una destinazione non vuota")
    parser.add_argument("--dry-run", action="store_true", help="Mostra solo i conteggi")
    args = parser.parse_args(argv)
    return restore(args.archive, args.prefix, args.dest, args.force, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
