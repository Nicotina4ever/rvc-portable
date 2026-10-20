"""Rotte cloud Dropbox: stato, App Key, OAuth PKCE, upload/download, disconnessione.

Il client (``app.cloud.dropbox.DropboxClient``) parla direttamente con le API
Dropbox via ``requests``; qui si gestisce solo la traduzione degli errori verso
l'envelope API e la cache del client su ``app.state`` (necessaria per conservare
il ``code_verifier`` PKCE tra ``authorize`` e ``complete``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from ...cloud.dropbox import CloudError, DropboxClient
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["cloud"])


def get_dropbox_client(request: Request) -> DropboxClient:
    """Client condiviso per app (uno per processo): conserva lo stato PKCE."""
    client = getattr(request.app.state, "dropbox_client", None)
    if client is not None:
        return client
    client = DropboxClient(deps.paths(request), deps.settings_manager(request))
    request.app.state.dropbox_client = client
    return client


def _call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except CloudError as exc:
        raise ApiError(
            exc.code, exc.message, exc.status_code, exc.params, exc.detail
        ) from exc


def _force(payload: Optional[Dict[str, Any]]) -> bool:
    return bool((payload or {}).get("force", False))


@router.get("/api/cloud/dropbox")
def dropbox_status(request: Request):
    return _call(get_dropbox_client(request).status)


@router.put("/api/cloud/dropbox/key")
def dropbox_set_key(
    request: Request,
    payload: Optional[Dict[str, Any]] = None,
):
    app_key = str((payload or {}).get("app_key") or "").strip()
    if not app_key:
        raise ApiError(
            "validation_error",
            "App Key Dropbox mancante: incolla la App Key della Scoped App",
            422,
            {"field": "app_key"},
        )
    return _call(get_dropbox_client(request).set_app_key, app_key)


@router.post("/api/cloud/dropbox/authorize")
def dropbox_authorize(request: Request):
    return _call(get_dropbox_client(request).authorize)


@router.post("/api/cloud/dropbox/complete")
def dropbox_complete(
    request: Request,
    payload: Optional[Dict[str, Any]] = None,
):
    code = str((payload or {}).get("code") or "").strip()
    if not code:
        raise ApiError(
            "dropbox_invalid_code",
            "Incolla il codice di autorizzazione mostrato da Dropbox",
            400,
            {"field": "code"},
        )
    return _call(get_dropbox_client(request).complete, code)


@router.post("/api/cloud/dropbox/upload")
def dropbox_upload(
    request: Request,
    payload: Optional[Dict[str, Any]] = None,
):
    return _call(get_dropbox_client(request).upload, _force(payload))


@router.post("/api/cloud/dropbox/download")
def dropbox_download(
    request: Request,
    payload: Optional[Dict[str, Any]] = None,
):
    return _call(get_dropbox_client(request).download, _force(payload))


@router.delete("/api/cloud/dropbox")
def dropbox_disconnect(request: Request):
    return _call(get_dropbox_client(request).disconnect)
