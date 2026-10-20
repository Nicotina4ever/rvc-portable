"""Rotte impostazioni: lettura, patch, import/export, percorsi."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ... import events
from ...settings import Settings
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["settings"])


def _snapshot(request: Request) -> Dict[str, Any]:
    manager = deps.settings_manager(request)
    settings = manager.settings
    return {
        "settings": settings.public_dict(),
        "warnings": list(manager.warnings),
        "problems": settings.validate_paths(),
        "config_path": manager.paths.config_path,
    }


def _body_settings(body: Any) -> Dict[str, Any]:
    if isinstance(body, dict) and "settings" in body and isinstance(body["settings"], dict):
        return body["settings"]
    if isinstance(body, dict):
        return body
    raise ApiError("settings_invalid", "Corpo JSON non valido")


def _export_shared(manager) -> None:
    """Se il ponte Android è attivo, allinea il config.json condiviso alle impostazioni PC."""
    try:
        from ...android_bridge import maybe_export_shared

        maybe_export_shared(manager)
    except Exception:  # pragma: no cover - non blocca il salvataggio
        pass


@router.get("/api/settings")
def get_settings(request: Request):
    return _snapshot(request)


@router.put("/api/settings")
async def put_settings(request: Request):
    body = await request.json()
    data = _body_settings(body)
    manager = deps.settings_manager(request)
    try:
        candidate = Settings(**data)
    except Exception as exc:
        raise ApiError("settings_invalid", "Impostazioni non valide", 422, {}, str(exc))
    try:
        manager.save(candidate)
    except Exception as exc:
        raise ApiError("settings_write_failed", "Salvataggio fallito", 500, {}, str(exc))
    _export_shared(manager)
    events.publish("config", source="api", path=manager.paths.config_path)
    return _snapshot(request)


@router.patch("/api/settings")
async def patch_settings(request: Request):
    body = await request.json()
    patch = body.get("patch") if isinstance(body, dict) and "patch" in body else body
    if not isinstance(patch, dict):
        raise ApiError("settings_invalid", "Patch non valida")
    manager = deps.settings_manager(request)
    try:
        manager.apply_patch(patch)
    except Exception as exc:
        raise ApiError("settings_invalid", "Impostazioni non valide", 422, {}, str(exc))
    _export_shared(manager)
    events.publish("config", source="api", path=manager.paths.config_path)
    return _snapshot(request)


@router.get("/api/settings/export")
def export_settings(request: Request):
    manager = deps.settings_manager(request)
    data = manager.export_dict()
    return JSONResponse(
        data,
        headers={
            "Content-Disposition": 'attachment; filename="rvc-portable-config.json"'
        },
    )


@router.post("/api/settings/import")
async def import_settings(request: Request):
    body = await request.json()
    data = _body_settings(body)
    manager = deps.settings_manager(request)
    try:
        manager.import_dict(data)
    except Exception as exc:
        raise ApiError("settings_invalid", "Import fallito", 422, {}, str(exc))
    _export_shared(manager)
    events.publish("config", source="import", path=manager.paths.config_path)
    return _snapshot(request)


@router.post("/api/settings/reveal")
async def reveal(request: Request):
    body = await request.json()
    target = str((body or {}).get("target", "data"))
    manager = deps.settings_manager(request)
    paths = manager.paths
    mapping = {
        "config": paths.config_path,
        "logs": paths.logs_dir,
        "data": paths.data_dir,
        "cache": paths.cache_dir,
    }
    path = mapping.get(target)
    if not path:
        raise ApiError("validation_error", "target non valido")
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise ApiError("not_found", "percorso non trovato", 404, {"path": path})

    threading.Thread(target=_open_in_file_manager, args=(path,), daemon=True).start()
    return {"path": path}


def _open_in_file_manager(path: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 - apertura esplicita richiesta dall'utente
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
