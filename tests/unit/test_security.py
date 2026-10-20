"""Test del middleware di sicurezza locale."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.security import LocalSecurityMiddleware

TOKEN = "token-di-prova"
PORT = 8123


async def handler(request):
    return JSONResponse({"ok": True})


def build_client(allow_lan: bool = False) -> TestClient:
    inner = Starlette(
        routes=[
            Route("/api/private", handler, methods=["GET", "POST"]),
            Route("/api/health", handler, methods=["GET"]),
            Route("/static/file.js", handler, methods=["GET"]),
            Route("/", handler, methods=["GET"]),
        ]
    )
    app = LocalSecurityMiddleware(
        inner, token=TOKEN, port=PORT, allow_lan=allow_lan
    )
    return TestClient(app, base_url="http://127.0.0.1:%d" % PORT)


def test_health_is_public():
    client = build_client()
    assert client.get("/api/health").status_code == 200


def test_private_requires_token():
    client = build_client()
    assert client.get("/api/private").status_code == 401
    response = client.get("/api/private", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_bearer_and_query_token():
    client = build_client()
    assert client.get("/api/private", headers={"Authorization": "Bearer %s" % TOKEN}).status_code == 200
    assert client.get("/api/private?t=%s" % TOKEN).status_code == 200


def test_foreign_origin_blocked_on_post():
    client = build_client()
    response = client.post(
        "/api/private",
        headers={"Authorization": "Bearer %s" % TOKEN, "Origin": "http://evil.test"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"


def test_foreign_host_blocked():
    inner = Starlette(routes=[Route("/api/health", handler, methods=["GET"])])
    app = LocalSecurityMiddleware(inner, token=TOKEN, port=PORT)
    client = TestClient(app, base_url="http://evil.test:%d" % PORT)
    assert client.get("/api/health").status_code == 403


def test_security_headers_present():
    client = build_client()
    response = client.get("/api/health")
    assert "content-security-policy" in {k.lower() for k in response.headers}
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"


def test_static_assets_do_not_require_token():
    client = build_client()
    assert client.get("/static/file.js").status_code == 200
