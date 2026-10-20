"""Scansione dei modelli RVC (.pth) e degli indici (.index).

Regole (contratto interno, docs/API-CONTRACT.md -> ``ModelEntry``):

- si esplorano le ``roots`` richieste (default: ``<app_root>/Modelli``) con
  ricorsione **limitata a 2 livelli**: abbastanza per le raccolte organizzate
  in sottocartelle, troppo poco per scansionare un intero disco;
- ogni ``.pth`` diventa un ``ModelEntry`` con euristica sul nome per associare
  l'indice ``.index`` corretto (prefissi ``added_``/``trained_``, coppie
  ``IVF<n>_Flat_nprobe_<n>``, suffissi ``_v1``/``_v2``);
- indice mancante o ambiguo producono ``warnings`` leggibili, mai errori;
- i file non vengono mai aperti in scrittura ne' modificati: solo ``stat``.

``default_index_hint`` e' il percorso dell'indice configurato dall'utente:
viene usato come fallback **solo** quando il nome combacia con il modello.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

LOGGER = logging.getLogger("rvc.model_scan")

MODEL_EXTENSION = ".pth"
INDEX_EXTENSION = ".index"
MAX_DEPTH = 2
SKIP_DIRS = {"__pycache__", ".git", ".svn", "node_modules", "$recycle.bin"}

_VERSION_RE = re.compile(r"(?:^|[_\-.])v(\d)(?:$|[_\-.])", re.IGNORECASE)
_IVF_PREFIX_RE = re.compile(
    r"^(?:added|trained)[_\-.]*ivf\d+[_\-.]+flat[_\-.]+nprobe[_\-.]+_?\d+[_\-.]+",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(r"^(?:added|trained)[_\-.]*", re.IGNORECASE)


def default_models_root() -> str:
    """``<app_root>/Modelli`` ricavato dalla posizione di questo modulo."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "Modelli")


def scan_models(
    roots: Optional[Iterable[str]] = None,
    default_index_hint: str = "",
) -> Dict[str, Any]:
    """Scansiona le radici e restituisce ``{"roots", "models", "warnings"}``."""
    warnings: List[str] = []
    root_list = _normalize_roots(roots, warnings)
    pth_files: List[str] = []
    index_files: List[str] = []

    for root in root_list:
        if not os.path.isdir(root):
            warnings.append("cartella modelli non trovata: %s" % root)
            continue
        found_models, found_indexes = _walk_root(root, warnings)
        pth_files.extend(found_models)
        index_files.extend(found_indexes)

    hint = _normalize_hint(default_index_hint, warnings)

    entries: List[Dict[str, Any]] = []
    used_indexes = set()
    for pth in _dedupe_sorted(pth_files):
        entry, matched = _build_entry(
            pth, index_files, used_indexes, hint, root_list, warnings
        )
        if matched:
            used_indexes.add(matched)
        entries.append(entry)

    entries.sort(key=lambda item: (item["name"].lower(), item["path"].lower()))
    return {"roots": root_list, "models": entries, "warnings": warnings}


def guess_version(path: str) -> str:
    """Versione RVC dedotta dal nome file, default ``v2``."""
    name = os.path.basename(str(path or ""))
    for match in _VERSION_RE.finditer(name):
        if match.group(1) in ("1", "2"):
            return "v" + match.group(1)
    lowered = name.lower()
    if "v1" in lowered:
        return "v1"
    return "v2"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _normalize_roots(roots: Optional[Iterable[str]], warnings: List[str]) -> List[str]:
    normalized: List[str] = []
    if roots:
        candidates = [str(item).strip() for item in roots if str(item or "").strip()]
    else:
        candidates = []
    if not candidates:
        candidates = [default_models_root()]
    for candidate in candidates:
        path = os.path.abspath(os.path.expanduser(candidate.strip().strip('"')))
        if path not in normalized:
            normalized.append(path)
    return normalized


def _normalize_hint(hint: str, warnings: List[str]) -> str:
    value = str(hint or "").strip().strip('"')
    if not value:
        return ""
    path = os.path.abspath(os.path.expanduser(value))
    if not os.path.isfile(path):
        warnings.append("indice predefinito non trovato: %s" % path)
        return ""
    return path


def _walk_root(root: str, warnings: List[str]) -> Tuple[List[str], List[str]]:
    models: List[str] = []
    indexes: List[str] = []
    base_depth = root.rstrip("\\/").count(os.sep)
    for current, dirnames, filenames in os.walk(root, onerror=lambda err: None):
        depth = current.rstrip("\\/").count(os.sep) - base_depth
        dirnames[:] = [
            name
            for name in dirnames
            if name.lower() not in SKIP_DIRS and not name.startswith(".")
        ]
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        for name in filenames:
            lowered = name.lower()
            if lowered.startswith("."):
                continue
            full = os.path.join(current, name)
            if lowered.endswith(MODEL_EXTENSION):
                models.append(full)
            elif lowered.endswith(INDEX_EXTENSION):
                indexes.append(full)
    return models, indexes


def _build_entry(
    pth_path: str,
    index_files: List[str],
    used_indexes: set,
    hint: str,
    roots: List[str],
    warnings: List[str],
) -> Tuple[Dict[str, Any], Optional[str]]:
    name = os.path.splitext(os.path.basename(pth_path))[0]
    entry_warnings: List[str] = []
    candidates = [
        index
        for index in index_files
        if index not in used_indexes and _index_matches(name, index)
    ]
    matched = ""
    if len(candidates) == 1:
        matched = candidates[0]
    elif len(candidates) > 1:
        matched, distinct = _pick_best_index(name, pth_path, candidates)
        if distinct > 1:
            entry_warnings.append(
                "piu' indici compatibili: uso %s" % os.path.basename(matched)
            )
    elif hint and _index_matches(name, hint) and hint not in used_indexes:
        matched = hint
        entry_warnings.append("indice assegnato dal percorso predefinito")

    if not matched:
        entry_warnings.append("indice opzionale assente")

    try:
        stat = os.stat(pth_path)
        size_mb = round(stat.st_size / (1024 * 1024), 1)
        mtime = float(stat.st_mtime)
    except OSError as exc:  # pragma: no cover - file rimosso durante la scansione
        warnings.append("modello illeggibile: %s (%s)" % (pth_path, exc))
        size_mb, mtime = 0.0, 0.0

    entry = {
        "name": name,
        "path": pth_path,
        "index_path": matched,
        "size_mb": size_mb,
        "version_guess": guess_version(pth_path),
        "source": _source_label(pth_path, roots),
        "has_index": bool(matched),
        "warnings": entry_warnings,
        "mtime": mtime,
    }
    return entry, matched or None


def _source_label(pth_path: str, roots: List[str]) -> str:
    normalized = os.path.normcase(os.path.abspath(pth_path))
    for root in roots:
        root_abs = os.path.abspath(root)
        root_norm = os.path.normcase(root_abs).rstrip("\\/")
        if normalized == root_norm or normalized.startswith(root_norm + os.sep):
            return os.path.basename(root_abs.rstrip("\\/")) or root_abs
    return os.path.dirname(pth_path)


def _same_dir(first: str, second: str) -> bool:
    try:
        return os.path.normcase(os.path.dirname(first)) == os.path.normcase(
            os.path.dirname(second)
        )
    except (TypeError, ValueError):  # pragma: no cover
        return False


def _index_matches(model_name: str, index_path: str) -> bool:
    """Euristica nome modello <-> nome indice (case-insensitive)."""
    return _match_score(model_name, index_path) > 0


def _match_score(model_name: str, index_path: str) -> int:
    """0 = nessun match, 1 = debole, 2 = contenimento, 3 = nome identico."""
    model_key = _normalize_key(model_name)
    index_key = _normalize_key(os.path.splitext(os.path.basename(index_path))[0])
    if not model_key or not index_key:
        return 0
    if model_key == index_key:
        return 3
    if len(model_key) >= 4 and len(index_key) >= 4:
        if model_key in index_key or index_key in model_key:
            return 2
    return 0


def _pick_best_index(
    model_name: str, pth_path: str, candidates: List[str]
) -> Tuple[str, int]:
    """Sceglie l'indice migliore fra i candidati (added > trained, stesso nome).

    Ritorna ``(percorso, numero_di_indici_logici_distinti)``.
    """

    def key(index_path: str) -> Tuple[int, int, int, int, str]:
        basename = os.path.basename(index_path).lower()
        is_added = 0 if basename.startswith("added") else 1
        same_dir = 0 if _same_dir(index_path, pth_path) else 1
        return (
            -_match_score(model_name, index_path),
            is_added,
            same_dir,
            len(basename),
            basename,
        )

    # Le varianti added_/trained_ dello stesso indice sono lo stesso file
    # logico: scegli la variante "added" senza generare un falso conflitto.
    grouped: Dict[str, List[str]] = {}
    for candidate in candidates:
        grouped.setdefault(_identity_key(candidate), []).append(candidate)
    representatives = [
        sorted(
            group,
            key=lambda item: (
                not os.path.basename(item).lower().startswith("added"),
                item.lower(),
            ),
        )[0]
        for group in grouped.values()
    ]
    representatives.sort(key=key)
    return representatives[0], len(grouped)


def _identity_key(index_path: str) -> str:
    return _normalize_key(os.path.splitext(os.path.basename(index_path))[0])


def _normalize_key(value: str) -> str:
    key = str(value or "").strip().lower()
    if not key:
        return ""
    key = _IVF_PREFIX_RE.sub("", key)
    key = _PREFIX_RE.sub("", key)
    key = re.sub(r"[_\-. ]?v[12]$", "", key)
    key = re.sub(r"[^a-z0-9]+", "", key)
    return key


def _dedupe_sorted(paths: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        result.append(os.path.abspath(path))
    return result
