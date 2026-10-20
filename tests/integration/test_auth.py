"""Test di integrazione del middleware di sicurezza sulle rotte di mia competenza."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

TOKEN = "integration-token"

PROTECTED = [
    ("GET", "/api/meta"),
    ("GET", "/api/system/diagnostics"),
    ("POST", "/api/system/shutdown"),
    ("GET", "/api/hardware"),
    ("GET", "/api/models"),
    ("POST", "/api/models/scan"),
    ("POST", "/api/models/probe"),
    ("POST", "/api/files/dialog"),
    ("GET", "/api/cloud/dropbox"),
    ("PUT", "/api/cloud/dropbox/key"),
    ("POST", "/api/cloud/dropbox/authorize"),
    ("POST", "/api/cloud/dropbox/complete"),
    ("POST", "/api/cloud/dropbox/upload"),
    ("POST", "/api/cloud/dropbox/download"),
    ("DELETE", "/api/cloud/dropbox"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_endpoints_require_token(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401, (method, path, response.text)
    assert response.json()["error"]["code"] == "unauthorized"


def test_query_token_is_accepted(client):
    response = client.get("/api/meta?t=%s" % TOKEN)
    assert response.status_code == 200, response.text


def test_wrong_token_is_rejected(client):
    response = client.get("/api/meta", headers={"Authorization": "Bearer sbagliato"})
    assert response.status_code == 401


def test_foreign_origin_is_rejected_on_mutation(client, auth):
    headers = dict(auth)
    headers["Origin"] = "http://evil.example"
    response = client.post("/api/system/shutdown", headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden_origin"


def test_foreign_host_is_rejected(client):
    response = client.get("/api/meta", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_host"


def test_same_origin_mutation_is_allowed(client, auth, app):
    headers = dict(auth)
    headers["Origin"] = "http://127.0.0.1:8877"
    headers["Sec-Fetch-Site"] = "same-origin"
    app.state.shutdown_callback = None
    response = client.post("/api/system/shutdown", headers=headers)
    assert response.status_code == 503, response.text


def test_security_headers_present(client, auth):
    response = client.get("/api/meta", headers=auth)
    assert response.headers.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in response.headers.get("content-security-policy", "")
    assert response.headers.get("x-content-type-options") == "nosniff"
