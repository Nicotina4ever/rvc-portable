"""Catalogo traduzioni servito alla SPA."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["locales"])


def _catalog(request: Request):
    return request.app.state.locales


@router.get("/api/locales")
def list_locales(request: Request):
    catalog = _catalog(request)
    return {"languages": catalog.available(), "default": "it"}


@router.get("/api/locales/{language}")
def get_locale(language: str, request: Request):
    catalog = _catalog(request)
    strings = catalog.load(language)
    return {"lang": catalog.language, "strings": strings}
