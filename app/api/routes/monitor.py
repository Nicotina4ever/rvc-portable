"""Rotte monitoraggio cartelle."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request

from ... import events
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["monitor"])


def _status(request: Request):
    try:
        return deps.watcher(request).status()
    except NotImplementedError:
        raise ApiError(
            "monitor_error", "Watcher non ancora implementato (teammate A)", 501
        )


@router.get("/api/monitor")
def monitor_status(request: Request):
    return _status(request)


@router.post("/api/monitor/start")
async def monitor_start(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    settings = deps.settings_manager(request).settings
    directory = str((body or {}).get("dir") or settings.audio.input_dir or "")
    if not directory or not os.path.isdir(directory):
        raise ApiError(
            "input_missing", "Cartella input non valida", 422, {"dir": directory}
        )
    process_existing = bool(
        (body or {}).get("process_existing", settings.monitor.process_existing)
    )
    try:
        status = deps.watcher(request).start(directory, process_existing=process_existing)
    except NotImplementedError:
        raise ApiError(
            "monitor_error", "Watcher non ancora implementato (teammate A)", 501
        )
    except Exception as exc:
        raise ApiError("monitor_error", str(exc), 500)
    events.publish("monitor", **status)
    return status


@router.post("/api/monitor/stop")
def monitor_stop(request: Request):
    try:
        status = deps.watcher(request).stop()
    except NotImplementedError:
        raise ApiError(
            "monitor_error", "Watcher non ancora implementato (teammate A)", 501
        )
    except Exception as exc:
        raise ApiError("monitor_error", str(exc), 500)
    events.publish("monitor", **status)
    return status


@router.post("/api/monitor/process-existing")
async def monitor_process_existing(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    settings = deps.settings_manager(request).settings
    directory = str((body or {}).get("dir") or settings.audio.input_dir or "")
    if not directory or not os.path.isdir(directory):
        raise ApiError(
            "input_missing", "Cartella input non valida", 422, {"dir": directory}
        )
    try:
        result = deps.watcher(request).process_existing(directory)
    except NotImplementedError:
        raise ApiError(
            "monitor_error", "Watcher non ancora implementato (teammate A)", 501
        )
    except Exception as exc:
        raise ApiError("monitor_error", str(exc), 500)
    return result
