"""Errori API uniformi (envelope ``{"error": {...}}``)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.engine import EngineError
from ..settings import SettingsError

LOGGER = logging.getLogger("rvc.api")

STATUS_BY_CODE = {
    "unauthorized": 401,
    "forbidden_origin": 403,
    "forbidden_host": 403,
    "not_found": 404,
    "validation_error": 422,
    "settings_invalid": 422,
    "settings_write_failed": 500,
    "engine_unavailable": 503,
    "engine_error": 500,
    "engine_busy": 409,
    "model_invalid": 422,
    "model_not_found": 404,
    "index_invalid": 422,
    "input_missing": 404,
    "output_dir_missing": 422,
    "job_not_found": 404,
    "job_running": 409,
    "monitor_error": 500,
    "cloud_error": 502,
    "dropbox_not_configured": 400,
    "dropbox_invalid_client": 400,
    "dropbox_invalid_code": 400,
    "dropbox_conflict": 409,
    "network_error": 502,
    "internal_error": 500,
}


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str = "",
        status_code: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        detail: str = "",
    ):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code or STATUS_BY_CODE.get(code, 400)
        self.params = params or {}
        self.detail = detail


def payload(code: str, message: str, params=None, detail: str = "") -> Dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "params": params or {},
            "detail": detail,
        }
    }


def _response(code: str, message: str, status_code=None, params=None, detail="") -> JSONResponse:
    return JSONResponse(
        status_code=status_code or STATUS_BY_CODE.get(code, 400),
        content=payload(code, message, params, detail),
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _response(exc.code, exc.message, exc.status_code, exc.params, exc.detail)

    @app.exception_handler(EngineError)
    async def _engine_error(_: Request, exc: EngineError):
        return _response(exc.code, exc.message, None, {}, exc.detail)

    @app.exception_handler(SettingsError)
    async def _settings_error(_: Request, exc: SettingsError):
        return _response("settings_invalid", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return _response(
            "validation_error",
            "Richiesta non valida",
            None,
            {"errors": _jsonable_errors(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else "internal_error"
        return _response(code, str(exc.detail), exc.status_code)

    @app.exception_handler(FileNotFoundError)
    async def _file_error(_: Request, exc: FileNotFoundError):
        return _response("input_missing", "File o cartella non trovata", 404, {"path": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError):
        return _response("validation_error", str(exc), 422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        LOGGER.exception("errore non gestito")
        return _response("internal_error", "Errore interno", 500, {}, repr(exc))


def _jsonable_errors(errors) -> Any:
    result = []
    for error in errors or []:
        result.append(
            {
                "loc": [str(part) for part in error.get("loc", [])],
                "msg": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
        )
    return result
