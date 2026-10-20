"""Rotte modelli: elenco, scansione cartelle e ispezione di percorsi espliciti.

La scansione vera e' in ``app.core.model_scan`` (modulo del motore). Fino a che
non e' disponibile il modulo solleva ``NotImplementedError``: qui viene tradotto
in ``503 model_invalid`` con un messaggio esplicito, cosi' la UI resta usabile.

Il backend non modifica mai i file dei modelli: sola lettura di metadati.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from ...core import model_scan
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["models"])

NOT_AVAILABLE_MESSAGE = (
    "Scansione modelli non ancora disponibile: riprova dopo l'aggiornamento "
    "dell'applicazione."
)


def _normalize(value: Any) -> str:
    text = str(value or "").strip().strip('"')
    return os.path.abspath(os.path.expanduser(text))


def _default_roots(request: Request) -> List[str]:
    paths = deps.paths(request)
    settings = deps.settings_manager(request).settings
    roots: List[str] = []
    models_dir = getattr(paths, "models_dir", "")
    if models_dir:
        roots.append(models_dir)
    for extra in getattr(settings.audio, "extra_model_dirs", []) or []:
        if extra and extra not in roots:
            roots.append(extra)
    return roots


def _default_root(request: Request) -> str:
    roots = _default_roots(request)
    return roots[0] if roots else deps.paths(request).models_dir


def _index_hint(request: Request) -> str:
    return str(deps.settings_manager(request).settings.audio.index_path or "")


def _resolve_roots(request: Request, raw_roots: Any) -> List[str]:
    default_roots = _default_roots(request)
    explicit = raw_roots is not None
    if raw_roots is None:
        roots = [root for root in default_roots if os.path.isdir(root)]
    elif isinstance(raw_roots, list):
        roots = []
        for item in raw_roots:
            if not isinstance(item, str) or not item.strip():
                raise ApiError(
                    "validation_error",
                    "Le cartelle modelli devono essere percorsi non vuoti",
                    422,
                    {"field": "roots"},
                )
            roots.append(_normalize(item))
        if not roots:
            roots = [root for root in default_roots if os.path.isdir(root)]
    else:
        raise ApiError(
            "validation_error",
            "Il campo 'roots' deve essere una lista di percorsi",
            422,
            {"field": "roots"},
        )
    if explicit:
        missing = [root for root in roots if not os.path.isdir(root)]
        if missing:
            raise ApiError(
                "validation_error",
                "Cartella modelli non trovata: %s" % ", ".join(missing),
                422,
                {"roots": missing},
            )
    return roots


def _normalize_scan_result(result: Any, roots: List[str]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise ApiError(
            "internal_error",
            "Risposta della scansione modelli non valida",
            500,
            {},
            "atteso dict da scan_models",
        )
    models = result.get("models")
    if not isinstance(models, list):
        models = []
    warnings = result.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    result_roots = result.get("roots")
    if not isinstance(result_roots, list) or not result_roots:
        result_roots = roots
    return {
        "roots": [str(item) for item in result_roots],
        "models": models,
        "warnings": [str(item) for item in warnings],
    }


def _run_scan(request: Request, raw_roots: Any) -> Dict[str, Any]:
    roots = _resolve_roots(request, raw_roots)
    if not roots:
        return {
            "roots": [],
            "models": [],
            "warnings": [
                "Cartella modelli non trovata: %s" % _default_root(request),
            ],
        }
    try:
        result = model_scan.scan_models(roots, _index_hint(request))
    except NotImplementedError as exc:
        raise ApiError(
            "model_invalid", NOT_AVAILABLE_MESSAGE, 503, {}, str(exc) or ""
        ) from exc
    except (OSError, ValueError) as exc:
        raise ApiError(
            "model_invalid",
            "Impossibile scansionare i modelli: %s" % exc,
            422,
            {},
            repr(exc),
        ) from exc
    return _normalize_scan_result(result, roots)


def _fallback_entry(path: str) -> Dict[str, Any]:
    """ModelEntry minimale per un file esplicitamente selezionato."""
    try:
        size_bytes = os.path.getsize(path)
    except OSError:
        size_bytes = 0
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    name, extension = os.path.splitext(os.path.basename(path))
    warnings = ["metadati del modello non riconosciuti"]
    if extension.lower() != ".pth":
        warnings.append("estensione non standard: attesa .pth")
    version = "v2"
    guess = getattr(model_scan, "guess_version", None)
    if callable(guess):
        try:
            version = str(guess(path) or "v2")
        except Exception:  # pragma: no cover - helper del motore
            version = "v2"
    parent = os.path.basename(os.path.dirname(path))
    return {
        "name": name,
        "path": path,
        "index_path": "",
        "size_mb": round(size_bytes / (1024 * 1024), 1),
        "version_guess": version,
        "source": parent or "manuale",
        "has_index": False,
        "warnings": warnings,
        "mtime": mtime,
    }


def _probe_entries(request: Request, raw_paths: Any) -> Dict[str, Any]:
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ApiError(
            "validation_error",
            "Serve una lista 'paths' non vuota",
            422,
            {"field": "paths"},
        )
    normalized: List[str] = []
    missing: List[str] = []
    for item in raw_paths:
        if not isinstance(item, str) or not item.strip():
            raise ApiError(
                "validation_error",
                "I percorsi devono essere stringhe non vuote",
                422,
                {"field": "paths"},
            )
        candidate = _normalize(item)
        if not os.path.isfile(candidate):
            missing.append(candidate)
        else:
            normalized.append(candidate)
    if missing:
        raise ApiError(
            "model_not_found",
            "File modello non trovato: %s" % ", ".join(missing),
            404,
            {"paths": missing},
        )
    unique: List[str] = []
    seen = set()
    for item in normalized:
        key = os.path.normcase(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    roots = sorted(
        {os.path.dirname(item) for item in unique}, key=lambda value: value.lower()
    )
    try:
        result = model_scan.scan_models(roots, _index_hint(request))
    except NotImplementedError as exc:
        raise ApiError(
            "model_invalid", NOT_AVAILABLE_MESSAGE, 503, {}, str(exc) or ""
        ) from exc
    except (OSError, ValueError) as exc:
        raise ApiError(
            "model_invalid",
            "Impossibile leggere i modelli: %s" % exc,
            422,
            {},
            repr(exc),
        ) from exc
    scanned = _normalize_scan_result(result, roots)
    index: Dict[str, Dict[str, Any]] = {}
    for entry in scanned["models"]:
        if not isinstance(entry, dict):
            continue
        entry_path = entry.get("path")
        if not entry_path:
            continue
        index[os.path.normcase(_normalize(entry_path))] = entry
    models: List[Dict[str, Any]] = []
    for item in unique:
        found = index.get(os.path.normcase(item))
        models.append(found if found is not None else _fallback_entry(item))
    return {"models": models}


@router.get("/api/models")
def list_models(request: Request):
    return _run_scan(request, None)


@router.post("/api/models/scan")
def scan_models(
    request: Request,
    payload: Optional[Dict[str, Any]] = None,
):
    body = payload or {}
    return _run_scan(request, body.get("roots"))


@router.post("/api/models/probe")
def probe_models(
    request: Request,
    payload: Optional[Dict[str, Any]] = None,
):
    body = payload or {}
    return _probe_entries(request, body.get("paths"))
