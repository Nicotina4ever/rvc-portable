"""Sicurezza del server locale: token, Host/Origin allowlist, header CSP.

Il backend ascolta solo su loopback. Anche cosi' applichiamo difese contro
richieste cross-site (il browser di un'altra pagina potrebbe tentare di
raggiungere 127.0.0.1): token obbligatorio, controllo Origin/Sec-Fetch-Site,
validazione Host e Content-Security-Policy senza inline script.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import stat
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set

from .paths import AppPaths

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
STATIC_PREFIXES = ("/css/", "/js/", "/assets/", "/locales/", "/img/")
EXEMPT_PATHS = {"/", "/index.html", "/favicon.ico", "/api/health"}

CSP_VALUE = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "media-src 'self' blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP_VALUE,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def new_token() -> str:
    return secrets.token_urlsafe(32)


def subprocess_no_window() -> Dict[str, int]:
    """Flag per non mostrare finestre console figlie su Windows."""
    if os.name != "nt":
        return {}
    import subprocess

    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@dataclass
class SessionInfo:
    token: str
    port: int
    pid: int
    started_at: float
    host: str = "127.0.0.1"

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "port": self.port,
            "pid": self.pid,
            "started_at": self.started_at,
            "host": self.host,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionInfo":
        return cls(
            token=str(data.get("token", "")),
            port=int(data.get("port", 0)),
            pid=int(data.get("pid", 0)),
            started_at=float(data.get("started_at", 0.0)),
            host=str(data.get("host", "127.0.0.1")),
        )


class SessionStore:
    """Persistenza del token di sessione (permessi ristretti)."""

    def __init__(self, paths: AppPaths):
        self.path = paths.session_path

    def save(self, session: SessionInfo) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = json.dumps(session.to_dict(), indent=2)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        _restrict_permissions(self.path)

    def load(self) -> Optional[SessionInfo]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return SessionInfo.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError):
            return None

    def clear(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass


def _restrict_permissions(path: str) -> None:
    try:
        if os.name == "posix":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


class LocalSecurityMiddleware:
    """Middleware ASGI: token + Host/Origin check + header di sicurezza."""

    def __init__(
        self,
        app,
        token: str,
        port: int,
        allow_lan: bool = False,
        extra_tokens: Optional[Iterable[str]] = None,
    ):
        self.app = app
        self._tokens: Set[str] = {token}
        for extra in extra_tokens or ():
            if extra:
                self._tokens.add(extra)
        self.port = port
        self.allow_lan = allow_lan
        self.allowed_origins = {
            "http://127.0.0.1:%d" % port,
            "http://localhost:%d" % port,
            "http://[::1]:%d" % port,
        }

    # ------------------------------------------------------------------ ASGI
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()

        if not self.allow_lan and not self._host_ok(headers):
            await _json_response(send, 403, "forbidden_host", "Host non consentito")
            return

        if method not in ("GET", "HEAD", "OPTIONS") and not self._origin_ok(headers):
            await _json_response(send, 403, "forbidden_origin", "Origin non consentito")
            return

        if self._needs_token(path) and not self._authorized(scope, headers):
            await _json_response(send, 401, "unauthorized", "Token mancante o non valido")
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                raw = list(message.get("headers", []))
                existing = {name.decode("latin-1").lower() for name, _ in raw}
                for name, value in SECURITY_HEADERS.items():
                    if name.lower() not in existing:
                        raw.append((name.encode("latin-1"), value.encode("latin-1")))
                message = dict(message)
                message["headers"] = raw
                if path == "/api/events":
                    message["headers"] = [
                        (n, v)
                        for n, v in message["headers"]
                        if n.decode("latin-1").lower() != "cache-control"
                    ] + [(b"cache-control", b"no-cache")]
            await send(message)

        await self.app(scope, receive, send_with_headers)

    # ---------------------------------------------------------------- checks
    def _host_ok(self, headers: Dict[str, str]) -> bool:
        host = (headers.get("host") or "").strip().lower()
        if not host:
            return False
        hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return hostname in LOCAL_HOSTS

    def _origin_ok(self, headers: Dict[str, str]) -> bool:
        origin = (headers.get("origin") or "").strip().lower()
        if origin and origin not in self.allowed_origins:
            return False
        fetch_site = (headers.get("sec-fetch-site") or "").strip().lower()
        if fetch_site and fetch_site not in ("same-origin", "none"):
            return False
        return True

    def _needs_token(self, path: str) -> bool:
        if path in EXEMPT_PATHS:
            return False
        if path.startswith(STATIC_PREFIXES):
            return False
        if path.startswith("/api/"):
            return True
        # html/spa e asset vari: nessun token (ma Origin resta controllato)
        return False

    def _authorized(self, scope, headers: Dict[str, str]) -> bool:
        auth = headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            candidate = auth[7:].strip()
            if self._token_ok(candidate):
                return True
        query = scope.get("query_string", b"").decode("latin-1")
        for pair in query.split("&"):
            if pair.startswith("t="):
                from urllib.parse import unquote

                if self._token_ok(unquote(pair[2:])):
                    return True
        return False

    def _token_ok(self, candidate: str) -> bool:
        if not candidate:
            return False
        for token in self._tokens:
            if hmac.compare_digest(candidate, token):
                return True
        return False


def _headers(scope) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for name, value in scope.get("headers", []):
        result[name.decode("latin-1").lower()] = value.decode("latin-1")
    return result


async def _json_response(send, status: int, code: str, message: str) -> None:
    body = json.dumps(
        {"error": {"code": code, "message": message, "params": {}}}
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
