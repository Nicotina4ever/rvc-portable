"""Quarantena dei file superflui: sposta in ``da_eliminare/`` con inventario.

Nessuna cancellazione (tranne le cache ``__pycache__``, rigenerabili).
Il comando e' idempotente e reversibile:

    python tools/quarantine.py                 # dry-run (default)
    python tools/quarantine.py --apply         # esegue gli spostamenti
    python tools/quarantine.py --restore       # ripristina i file spostati
    python tools/quarantine.py --only versione # solo una voce

Intoccabili (mai spostati): Modelli/, Progetto/Articolo Blog/, runtime/,
app/, web/, tools/, tests/, docs/ (tranne destinazioni esplicite), data/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUARANTINE = os.path.join(ROOT, "da_eliminare")
MANIFEST = os.path.join(QUARANTINE, "quarantine-manifest.json")
INVENTORY = os.path.join(QUARANTINE, "INVENTARIO.md")
CLEANUP_LOG = os.path.join(ROOT, "docs", "CLEANUP-LOG.md")

PROTECTED_PREFIXES = (
    "Modelli",
    "Progetto/Articolo Blog",
    "runtime",
    "app",
    "web",
    "locales",
    "tools",
    "tests",
    "docs",
    "data",
    ".dev",
    ".github",
    "da_eliminare",
)


def _entries() -> List[Dict[str, str]]:
    """Manifest dichiarativo: id, kind, src, dest, motivo."""
    items: List[Dict[str, str]] = []

    def add(entry_id, kind, src, dest, reason):
        items.append(
            {
                "id": entry_id,
                "kind": kind,
                "src": src,
                "dest": dest,
                "reason": reason,
            }
        )

    # Codice della versione 2.0 (sostituito dal package app/)
    add(
        "versione-2.0-snapshot",
        "record",
        "da_eliminare/_snapshot-pre-3.0",
        "da_eliminare/_snapshot-pre-3.0",
        "snapshot pre-refactor (riferimento)",
    )
    for name in (
        "app.py",
        "rvc_engine.py",
        "config_manager.py",
        "cloud_sync.py",
        "file_monitor.py",
        "i18n.py",
        "setup_wizard.py",
        "setup_hardware.bat",
    ):
        add("versione-2.0/" + name, "file", name, "versione-2.0/" + name, "sostituito da app/ e launcher 3.0")
    add("versione-2.0/lang", "dir", "lang", "versione-2.0/lang", "sostituito da locales/")
    add(
        "versione-2.0/config.json",
        "file",
        "config.json",
        "versione-2.0/config.json",
        "migrato in data/config.json (schema v3)",
    )

    # Requisiti obsoleti
    for name in ("requirements-win.txt", "requirements-wsl.txt", "requirements-updated.txt"):
        add(
            "requirements-precedenti/" + name,
            "file",
            name,
            "requirements-precedenti/" + name,
            "sostituito da requirements/{base,engine-*}.txt",
        )

    # Documentazione storica (in docs/archive, non in quarantena)
    add("docs/archive/NOTE-2025-06.md", "file", "Note.txt", "../docs/archive/NOTE-2025-06.md", "storico utile")
    add(
        "docs/GUIDA-INDEX-REPLAY.md",
        "file",
        "Per Index Replay.txt",
        "../docs/GUIDA-INDEX-REPLAY.md",
        "guida ancora valida",
    )
    add(
        "docs/archive/walkthrough-2026-10.md",
        "file",
        "walkthrough.md",
        "../docs/archive/walkthrough-2026-10.md",
        "storico del progetto",
    )
    add(
        "docs/archive/piano-refactoring-v2.md",
        "file",
        "piano-refactoring-rvc-portable.md",
        "../docs/archive/piano-refactoring-v2.md",
        "storico del progetto",
    )
    add(
        "documentazione-precedente/Readme.txt",
        "file",
        "Readme.txt",
        "documentazione-precedente/Readme.txt",
        "sostituito da README.md",
    )

    # Cartelle obsolete
    add("backup-2025", "dir", "Backup", "backup-2025", "duplicati/superati (giugno 2025)")
    add("test-2025", "dir", "Test", "test-2025", "archivio di test storico")
    add("legacy-2025", "dir", "legacy", "legacy-2025", "script superati dalla versione 3.0")
    add(
        "strumenti-obsoleti",
        "dir",
        "Inserire nella cartella cloud",
        "strumenti-obsoleti/Inserire nella cartella cloud",
        "editor HTML sostituito dalla UI Cloud",
    )

    # Vecchie distribuzioni
    add(
        "distribuzioni-precedenti/00-Replay",
        "dir",
        "Progetto/Inviare Per MacOS/00 - Replay per Addestrare Modello (user friendly)",
        "distribuzioni-precedenti/00-Replay",
        "installer Replay (strumento terzo, non distribuzione nostra)",
    )
    add(
        "distribuzioni-precedenti/01-RVC-Portable-MacOS",
        "dir",
        "Progetto/Inviare Per MacOS/01 - RVC Portable per MacOS (compilato su Sequoia Virtual Machine)",
        "distribuzioni-precedenti/01-RVC-Portable-MacOS",
        "vecchia distribuzione macOS (python pkg + venv)",
    )
    add(
        "distribuzioni-precedenti/Linux.zip",
        "file",
        "Progetto/Linux.zip",
        "distribuzioni-precedenti/Linux.zip",
        "vecchia distribuzione Linux",
    )
    add(
        "distribuzioni-precedenti/python-3.10.0post2-macos11.pkg",
        "file",
        "Progetto/python-3.10.0post2-macos11.pkg",
        "distribuzioni-precedenti/python-3.10.0post2-macos11.pkg",
        "installer Python per vecchia distribuzione macOS",
    )
    add(
        "distribuzioni-precedenti/RVC-Portable-per-MacOS.mp4",
        "file",
        "Progetto/RVC Portable per MacOS.mp4",
        "distribuzioni-precedenti/RVC-Portable-per-MacOS.mp4",
        "video della vecchia distribuzione (docs/img basta)",
    )
    add(
        "distribuzioni-precedenti/RVC-Portable_MacOS_Compilato.zip",
        "file",
        "Progetto/RVC-Portable_MacOS_Compilato.zip",
        "distribuzioni-precedenti/RVC-Portable_MacOS_Compilato.zip",
        "vecchia distribuzione macOS",
    )
    add(
        "distribuzioni-precedenti/RVC-PortableConMonitoraggio.zip",
        "file",
        "Progetto/RVC-PortableConMonitoraggio.zip",
        "distribuzioni-precedenti/RVC-PortableConMonitoraggio.zip",
        "vecchia distribuzione completa (runtime gia' ripristinato)",
    )

    # Modello della vecchia distribuzione: conservato, non in quarantena
    add(
        "Modelli/Archivio/Paolo",
        "contents",
        "Progetto/Inviare Per MacOS/02 - Modello per Esperimenti Paolo (creato da demo)",
        "../Modelli/Archivio/Paolo",
        "modello conservato: spostato tra i modelli, mai eliminato",
    )

    # Cache
    add("cache/__pycache__", "cache", "__pycache__", "", "cache Python rigenerabile")
    add("cache/lang-__pycache__", "cache", "lang/__pycache__", "", "cache Python rigenerabile")

    # Runtime 3.12 gia' spostato manualmente dopo la validazione del nuovo runtime
    add(
        "runtime-python312-windows",
        "record",
        "runtime (Python 3.12, pre-3.0)",
        "da_eliminare/runtime-python312-windows",
        "runtime incompatibile col motore; nuovo runtime 3.9 in runtime/",
    )
    return items


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


def _absolute(relative: str) -> str:
    if relative.startswith("../"):
        return os.path.abspath(os.path.join(QUARANTINE, relative))
    return os.path.abspath(os.path.join(QUARANTINE, relative))


def _src_absolute(relative: str) -> str:
    return os.path.abspath(os.path.join(ROOT, relative))


def _dest_absolute(entry: Dict[str, str]) -> str:
    if not entry["dest"]:
        return ""
    if entry["dest"].startswith("../"):
        return os.path.abspath(os.path.join(QUARANTINE, entry["dest"]))
    return os.path.abspath(os.path.join(QUARANTINE, entry["dest"]))


def _status(entry: Dict[str, str]) -> str:
    if entry["kind"] == "record":
        return (
            "registrato"
            if os.path.exists(os.path.join(ROOT, entry["dest"]))
            else "assente"
        )
    if entry["kind"] == "cache":
        return "presente" if os.path.exists(_src_absolute(entry["src"])) else "assente"
    dest = _dest_absolute(entry)
    src = _src_absolute(entry["src"])
    if os.path.exists(src):
        return "da-spostare"
    if dest and os.path.exists(dest):
        return "spostato"
    return "assente"


def _protected(src_relative: str) -> Optional[str]:
    normalised = src_relative.replace("\\", "/")
    for prefix in PROTECTED_PREFIXES:
        if normalised == prefix or normalised.startswith(prefix + "/"):
            # eccezioni esplicite gestite altrove (snapshot, docs destinazione)
            if normalised.startswith("da_eliminare/_snapshot"):
                return None
            return prefix
    return None


def _app_running() -> bool:
    instance = os.path.join(ROOT, "data", "state", "instance.json")
    if not os.path.isfile(instance):
        return False
    try:
        with open(instance, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        pid = int(data.get("pid", 0))
    except (OSError, ValueError, TypeError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _load_manifest() -> Dict[str, dict]:
    if not os.path.isfile(MANIFEST):
        return {}
    try:
        with open(MANIFEST, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {item["id"]: item for item in data.get("entries", [])}
    except (OSError, ValueError, KeyError):
        return {}


def _save_manifest(entries: List[dict]) -> None:
    os.makedirs(QUARANTINE, exist_ok=True)
    payload = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "entries": entries}
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _write_inventory(items: List[dict]) -> None:
    lines = [
        "# Inventario quarantena",
        "",
        "File spostati dalla riorganizzazione 3.0. **Nessun file e' stato cancellato**:",
        "questa cartella puo' essere ripristinata o svuotata quando vuoi.",
        "",
        "Ripristino: `python tools/quarantine.py --restore`",
        "",
        "| Stato | Dimensione | Origine | Destinazione | Motivo |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        src = item["src"]
        dest = item["dest"] or "—"
        size = item.get("size_mb")
        size_text = "%.1f MB" % size if size else "—"
        lines.append(
            "| %s | %s | `%s` | `%s` | %s |"
            % (item["status"], size_text, src, dest, item["reason"])
        )
    lines.append("")
    with open(INVENTORY, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _append_cleanup_log(action: str, moved: int, errors: int) -> None:
    os.makedirs(os.path.dirname(CLEANUP_LOG), exist_ok=True)
    header = not os.path.isfile(CLEANUP_LOG)
    with open(CLEANUP_LOG, "a", encoding="utf-8") as handle:
        if header:
            handle.write("# Pulizia e riordino — log\n\n")
        handle.write(
            "- %s — %s: %d voci, %d errori\n"
            % (time.strftime("%Y-%m-%d %H:%M:%S"), action, moved, errors)
        )


def plan(entries: List[Dict[str, str]]) -> None:
    print("%-8s %-10s %-12s %s" % ("STATO", "DIM.", "TIPO", "ORIGINE -> DESTINAZIONE"))
    for entry in entries:
        status = _status(entry)
        size = _size(_src_absolute(entry["src"])) if os.path.exists(_src_absolute(entry["src"])) else 0
        print(
            "%-8s %-10s %-12s %s -> %s"
            % (
                status,
                "%.1f MB" % (size / 1024 / 1024) if size else "—",
                entry["kind"],
                entry["src"],
                entry["dest"] or "—",
            )
        )


def apply(entries: List[Dict[str, str]], only: str = "") -> int:
    if _app_running():
        print("Applicazione in esecuzione: chiudi RVC Portable prima di riordinare.")
        return 3
    os.makedirs(QUARANTINE, exist_ok=True)
    moved = 0
    errors = 0
    for entry in entries:
        if only and only not in entry["id"]:
            continue
        status = _status(entry)
        if status in ("assente", "spostato", "registrato"):
            continue
        src = _src_absolute(entry["src"])
        dest = _dest_absolute(entry)
        try:
            if entry["kind"] == "cache":
                shutil.rmtree(src, ignore_errors=True)
                moved += 1
                continue
            if entry["kind"] == "record":
                moved += 1
                continue
            if entry["kind"] == "contents":
                os.makedirs(dest, exist_ok=True)
                for name in os.listdir(src):
                    shutil.move(os.path.join(src, name), os.path.join(dest, name))
                if not os.listdir(src):
                    os.rmdir(src)
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if os.path.exists(dest):
                    raise FileExistsError("destinazione gia' esistente: %s" % dest)
                shutil.move(src, dest)
            moved += 1
            print("spostato: %s -> %s" % (entry["src"], entry["dest"]))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print("ERRORE su %s: %s" % (entry["src"], exc))
    _cleanup_empty_dirs()
    _append_cleanup_log("apply", moved, errors)
    _refresh(entries)
    return 0 if errors == 0 else 1


def restore(entries: List[Dict[str, str]], only: str = "") -> int:
    restored = 0
    errors = 0
    for entry in reversed(entries):
        if only and only not in entry["id"]:
            continue
        if entry["kind"] in ("cache", "record"):
            continue
        dest = _dest_absolute(entry)
        src = _src_absolute(entry["src"])
        if not dest or not os.path.exists(dest):
            continue
        try:
            if entry["kind"] == "contents":
                os.makedirs(src, exist_ok=True)
                for name in os.listdir(dest):
                    shutil.move(os.path.join(dest, name), os.path.join(src, name))
                os.rmdir(dest)
            else:
                os.makedirs(os.path.dirname(src), exist_ok=True)
                if os.path.exists(src):
                    raise FileExistsError("origine gia' esistente: %s" % src)
                shutil.move(dest, src)
            restored += 1
            print("ripristinato: %s" % entry["src"])
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print("ERRORE ripristino %s: %s" % (entry["src"], exc))
    _append_cleanup_log("restore", restored, errors)
    _refresh(entries)
    return 0 if errors == 0 else 1


def _refresh(entries: List[Dict[str, str]]) -> None:
    previous = _load_manifest()
    items = []
    for entry in entries:
        size = 0
        if entry["kind"] == "record":
            candidate = os.path.join(ROOT, entry["dest"])
            if os.path.exists(candidate):
                size = _size(candidate)
        else:
            src = _src_absolute(entry["src"])
            dest = _dest_absolute(entry)
            for candidate in (src, dest):
                if candidate and os.path.exists(candidate):
                    size = _size(candidate)
                    break
        item = {
            "id": entry["id"],
            "kind": entry["kind"],
            "src": entry["src"],
            "dest": entry["dest"],
            "reason": entry["reason"],
            "status": _status(entry),
            "size_mb": round(size / 1024 / 1024, 2) if size else 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        item["previous"] = previous.get(entry["id"], {}).get("status")
        items.append(item)
    _save_manifest(items)
    _write_inventory(items)


def _cleanup_empty_dirs() -> None:
    for base, _dirs, _files in os.walk(os.path.join(ROOT, "Progetto"), topdown=False):
        if "Articolo Blog" in base:
            continue
        if base == os.path.join(ROOT, "Progetto"):
            continue
        try:
            if not os.listdir(base):
                os.rmdir(base)
                print("rimossa cartella vuota: %s" % os.path.relpath(base, ROOT))
        except OSError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Quarantena file superflui (nessuna cancellazione)")
    parser.add_argument("--apply", action="store_true", help="esegue gli spostamenti")
    parser.add_argument("--restore", action="store_true", help="ripristina i file spostati")
    parser.add_argument("--only", default="", help="limita a un prefisso di id")
    parser.add_argument("--json", action="store_true", help="stampa il manifest JSON")
    args = parser.parse_args(argv)

    entries = _entries()
    invalid = [e for e in entries if e["kind"] != "record" and _protected(e["src"])]
    if invalid:
        print("ERRORE: voci che toccano percorsi protetti:")
        for entry in invalid:
            print("  - %s (%s)" % (entry["src"], entry["reason"]))
        return 4

    if args.restore:
        return restore(entries, args.only)
    if args.apply:
        return apply(entries, args.only)
    plan(entries)
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    print("\nDry-run: usa --apply per eseguire, --restore per tornare indietro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
