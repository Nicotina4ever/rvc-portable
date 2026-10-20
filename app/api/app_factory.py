"""Factory dell'applicazione FastAPI locale."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import FastAPI, Request

from .. import __version__
from ..events import EventBus
from ..i18n import LocaleCatalog
from ..paths import AppPaths
from ..security import LocalSecurityMiddleware
from ..settings import SettingsManager
from .errors import install_error_handlers
from .routes import (
    android,
    cloud,
    events,
    files,
    hardware,
    jobs,
    locales,
    models,
    monitor,
    system,
)
from .routes import (
    settings as settings_routes,
)
from .static import mount_static

LOGGER = logging.getLogger("rvc.api")


def create_app(
    *,
    paths: AppPaths,
    settings_manager: SettingsManager,
    engine: Any,
    job_queue: Any,
    watcher: Any,
    bus: Optional[EventBus] = None,
    token: str,
    port: int,
    started_at: Optional[float] = None,
    allow_lan: bool = False,
) -> FastAPI:
    app = FastAPI(
        title="RVC Portable API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.state.paths = paths
    app.state.settings_manager = settings_manager
    app.state.engine = engine
    app.state.job_queue = job_queue
    app.state.watcher = watcher
    app.state.token = token
    app.state.port = port
    app.state.started_at = started_at or time.time()
    app.state.allow_lan = allow_lan
    app.state.locales = LocaleCatalog(paths.locales_dir)
    app.state.bus = bus or EventBus()
    app.state.shutdown_callback = None

    app.add_middleware(
        LocalSecurityMiddleware,
        token=token,
        port=port,
        allow_lan=allow_lan,
    )
    install_error_handlers(app)

    @app.get("/api/health", include_in_schema=False)
    def health(_: Request):
        return {
            "status": "ok",
            "version": __version__,
            "uptime_s": round(time.time() - app.state.started_at, 1),
            "engine_available": bool(getattr(app.state.engine.status(), "available", False)),
        }

    for module in (
        system,
        settings_routes,
        hardware,
        models,
        files,
        jobs,
        monitor,
        cloud,
        android,
        locales,
    ):
        app.include_router(module.router)
    app.include_router(events.router)

    mount_static(app, paths)
    LOGGER.info("app FastAPI creata (token attivo, porta %s)", port)
    return app
