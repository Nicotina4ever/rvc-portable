"""Rotte del ponte Android/Dropbox (cartella locale sincronizzata).

Endpoints:
- ``GET  /api/android``           stato (Dropbox rilevati, percorsi, file, sync)
- ``POST /api/android/detect``    elenco cartelle Dropbox/candidate
- ``POST /api/android/preset``    prepara AudioIn/AudioOut, modelli.txt e config.json
- ``POST /api/android/sync``      riscrive modelli.txt e config.json condiviso
- ``POST /api/android/import``    applica subito il config.json condiviso

Nessuna chiamata di rete: la cartella è quella sincronizzata dal client Dropbox.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from ...android_bridge import (
    AndroidBridgeError,
    apply_payload,
    detect_dropbox_roots,
    import_shared_config,
    prepare,
    read_json_file,
    suggest_shared_dir,
    sync_shared,
)
from ...android_bridge import (
    status as bridge_status,
)
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["android"])
LOGGER = logging.getLogger("rvc.api")

_ERROR_STATUS = {
    "android_not_configured": 422,
    "android_dropbox_missing": 422,
    "android_write_failed": 500,
    "android_config_missing": 404,
    "android_config_invalid": 422,
}


def _fail(exc: AndroidBridgeError):
    raise ApiError(
        exc.code,
        exc.message,
        _ERROR_STATUS.get(exc.code, 500),
        {},
        "",
    )


def _config_sync(request: Request):
    return getattr(request.app.state, "config_sync", None)


@router.get("/api/android")
def android_status(request: Request):
    manager = deps.settings_manager(request)
    return bridge_status(manager, deps.paths(request), _config_sync(request))


@router.post("/api/android/detect")
def android_detect():
    return {
        "roots": detect_dropbox_roots(),
        "suggested_shared_dir": suggest_shared_dir(),
    }


@router.post("/api/android/preset")
async def android_preset(request: Request):
    body: Dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    shared_dir = str((body or {}).get("shared_dir") or "").strip()
    manager = deps.settings_manager(request)
    try:
        summary = prepare(
            manager,
            deps.paths(request),
            shared_dir=shared_dir,
            watcher=deps.watcher(request),
        )
    except AndroidBridgeError as exc:
        _fail(exc)
    deps.bus(request).publish(
        "config", {"source": "android-preset", "shared_dir": shared_dir}
    )
    deps.bus(request).publish("monitor", {"preset": "android"})
    return {
        "ok": True,
        "summary": summary,
        "status": bridge_status(manager, deps.paths(request), _config_sync(request)),
    }


@router.post("/api/android/sync")
def android_sync(request: Request):
    manager = deps.settings_manager(request)
    try:
        summary = sync_shared(manager, deps.paths(request))
    except AndroidBridgeError as exc:
        _fail(exc)
    deps.bus(request).publish(
        "config", {"source": "android-sync", "models": summary.get("models")}
    )
    return {"ok": True, "summary": summary}


@router.post("/api/android/import")
def android_import(request: Request):
    manager = deps.settings_manager(request)
    try:
        result = import_shared_config(manager)
    except AndroidBridgeError as exc:
        _fail(exc)
    deps.bus(request).publish(
        "config",
        {
            "source": "android-import",
            "applied": result.get("applied", []),
            "skipped": result.get("skipped", []),
        },
    )
    return {"ok": True, "result": result}


@router.put("/api/android/config")
async def android_write_config(request: Request):
    """Applica un payload config (piatto Android o v3) senza file su disco."""
    body: Optional[Dict[str, Any]] = None
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise ApiError("validation_error", "Atteso un oggetto JSON", 422, {"field": "body"})
    manager = deps.settings_manager(request)
    try:
        result = apply_payload(manager, body)
    except AndroidBridgeError as exc:
        _fail(exc)
    deps.bus(request).publish(
        "config", {"source": "android-api", "applied": result.get("applied")}
    )
    return {"ok": True, "result": result}


@router.get("/api/android/config")
def android_read_config(request: Request):
    manager = deps.settings_manager(request)
    from ...android_bridge import shared_paths

    paths = shared_paths(manager.settings.android.shared_dir, manager.settings.android)
    payload = read_json_file(paths["config_path"]) if paths["config_path"] else None
    return {"path": paths["config_path"], "payload": payload}
