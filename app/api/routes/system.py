"""Rotte di sistema: meta, diagnostica, spegnimento.

Endpoint del contratto (``docs/API-CONTRACT.md``):
    GET  /api/meta
    GET  /api/system/diagnostics?force=false
    POST /api/system/shutdown
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
import time
from typing import Any, Dict

from fastapi import APIRouter, Request

from ... import __app_name__, __suite_name__, __version__, doctor
from ...core.engine import EngineStatus
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["system"])

LOGGER = logging.getLogger("rvc.api")


def _uptime(request: Request) -> float:
    started_at = getattr(request.app.state, "started_at", None) or time.time()
    return round(max(0.0, time.time() - started_at), 1)


def _engine_status(request: Request) -> Dict[str, Any]:
    engine = deps.engine(request)
    try:
        return engine.status().to_dict()
    except Exception as exc:  # pragma: no cover - motore in stato inconsistente
        LOGGER.warning("stato motore non leggibile: %s", exc)
        return EngineStatus(
            available=False,
            code="engine_unavailable",
            message="Stato del motore non disponibile: %s" % exc,
        ).to_dict()


@router.get("/api/meta")
def get_meta(request: Request):
    paths = deps.paths(request)
    started_at = getattr(request.app.state, "started_at", None) or time.time()
    return {
        "app": __app_name__,
        "suite": __suite_name__,
        "version": __version__,
        "python": sys.version,
        "platform": sys.platform,
        "platform_label": platform.platform(),
        "paths": paths.describe(),
        "engine": _engine_status(request),
        "started_at": started_at,
        "uptime_s": _uptime(request),
    }


@router.get("/api/system/diagnostics")
def get_diagnostics(request: Request, force: bool = False):
    paths = deps.paths(request)
    settings = deps.settings_manager(request).settings
    return doctor.run_checks(paths, settings, force_probe=bool(force))


def _invoke_shutdown(callback) -> None:
    """Spegne l'app in un thread, lasciando completare la risposta HTTP."""
    time.sleep(0.1)
    try:
        callback()
    except Exception:  # pragma: no cover - callback del launcher
        LOGGER.exception("callback di spegnimento fallita")


@router.post("/api/system/shutdown")
def post_shutdown(request: Request):
    callback = getattr(request.app.state, "shutdown_callback", None)
    if not callable(callback):
        raise ApiError(
            "engine_unavailable",
            "Spegnimento non disponibile: avvia l'app con il launcher",
            503,
        )
    threading.Thread(
        target=_invoke_shutdown,
        args=(callback,),
        name="rvc-shutdown",
        daemon=True,
    ).start()
    return {"ok": True}
