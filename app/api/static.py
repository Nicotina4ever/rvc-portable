"""Servizio dei file statici della SPA (nessun build step)."""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from ..paths import AppPaths

STATIC_DIRS = {
    "/css": "css",
    "/js": "js",
    "/assets": "assets",
    "/locales": "locales",
}


def mount_static(app: FastAPI, paths: AppPaths) -> None:
    web_dir = paths.web_dir
    for prefix, folder in STATIC_DIRS.items():
        directory = os.path.join(web_dir, folder) if folder != "locales" else paths.locales_dir
        if os.path.isdir(directory):
            app.mount(prefix, StaticFiles(directory=directory), name="static-" + folder)

    index_path = os.path.join(web_dir, "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        icon = os.path.join(web_dir, "assets", "icon.svg")
        if os.path.isfile(icon):
            return FileResponse(icon, media_type="image/svg+xml")
        return RedirectResponse(url="/assets/icon.svg")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        # Le rotte /api sono gestite prima; qui servono solo asset e SPA.
        candidate = os.path.normpath(os.path.join(web_dir, full_path))
        if (
            full_path
            and candidate.startswith(os.path.abspath(web_dir) + os.sep)
            and os.path.isfile(candidate)
        ):
            return FileResponse(candidate)
        if not os.path.isfile(index_path):
            return RedirectResponse(url="/api/health")
        return FileResponse(index_path, media_type="text/html; charset=utf-8")
