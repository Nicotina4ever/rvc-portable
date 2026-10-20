"""Test di integrazione per le rotte cloud Dropbox.

La rete e' SEMPRE simulata: ``DropboxClient`` riceve una session factory finta
che risponde in base a una coda di handler programmati dal test. Nessuna
richiesta reale a Dropbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from app.cloud.dropbox import (
    AUTHORIZE_URL,
    CONTENT_BASE,
    TOKEN_URL,
    DropboxClient,
    code_challenge,
    generate_code_verifier,
)

pytestmark = pytest.mark.integration

CHECK_COMPLETE = "/api/cloud/dropbox/complete"
URL_METADATA = "https://api.dropboxapi.com/2/files/get_metadata"
URL_ACCOUNT = "https://api.dropboxapi.com/2/users/get_current_account"
URL_UPLOAD = CONTENT_BASE + "files/upload"
URL_DOWNLOAD = CONTENT_BASE + "files/download"
REMOTE_DEFAULT = "/NLTools/RVC/config.json"


# ---------------------------------------------------------------------------
# Transport HTTP finto
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = dict(headers or {})


class Call:
    def __init__(self, method, url, headers, data, json_body, timeout):
        self.method = method
        self.url = url
        self.headers = dict(headers or {})
        self.data = data
        self.json = json_body
        self.timeout = timeout


class FakeSession:
    def __init__(self, http):
        self.http = http
        self.closed = False

    def request(self, method, url, headers=None, data=None, json=None, timeout=None):
        return self.http.handle(
            method, url, headers=headers, data=data, json=json, timeout=timeout
        )

    def close(self):
        self.closed = True


class FakeHttp:
    """Coda di risposte: ogni handler consuma una richiesta, in ordine."""

    def __init__(self):
        self.calls = []
        self.queue = []
        self.sleeps = []

    def expect(self, handler):
        self.queue.append(handler)
        return self

    def session(self):
        return FakeSession(self)

    def handle(self, method, url, headers=None, data=None, json=None, timeout=None):
        call = Call(method, url, headers, data, json, timeout)
        self.calls.append(call)
        if not self.queue:
            raise AssertionError("richiesta HTTP non attesa: %s %s" % (method, url))
        handler = self.queue.pop(0)
        return handler(call)


def json_ok(payload, headers=None):
    return FakeResponse(200, json.dumps(payload).encode("utf-8"), headers)


def json_error(status_code, payload):
    return FakeResponse(status_code, json.dumps(payload).encode("utf-8"))


def token_payload(
    access: str = "access-token-1",
    refresh: str = "refresh-token-1",
    expires_in: int = 14400,
):
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
        "token_type": "bearer",
        "account_id": "dbid:1234",
    }


def account_payload(name: str = "Mario Rossi"):
    return {
        "account_id": "dbid:1234",
        "name": {"display_name": name, "given_name": "Mario", "surname": "Rossi"},
        "email": "mario@example.com",
    }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture()
def dropbox(app, manager, http) -> DropboxClient:
    client = DropboxClient(
        app.state.paths,
        manager,
        session_factory=http.session,
        sleep=http.sleeps.append,
        timeout=15.0,
    )
    app.state.dropbox_client = client
    return client


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def put_key(api, auth, key="test-app-key"):
    response = api.put("/api/cloud/dropbox/key", json={"app_key": key}, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def authorize(api, auth):
    response = api.post("/api/cloud/dropbox/authorize", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def auth_query(auth_url: str):
    assert auth_url.startswith(AUTHORIZE_URL + "?")
    return parse_qs(urlparse(auth_url).query)


def queue_connect(http, account="Mario Rossi"):
    seen = {}

    def token_handler(call):
        seen["verifier"] = str((call.data or {}).get("code_verifier") or "")
        return json_ok(token_payload())

    def account_handler(call):
        return json_ok(account_payload(account))

    http.expect(token_handler)
    http.expect(account_handler)
    return seen


def connect(api, auth, http, account="Mario Rossi"):
    put_key(api, auth)
    auth_data = authorize(api, auth)
    seen = queue_connect(http, account)
    response = api.post(CHECK_COMPLETE, json={"code": "auth-code-123"}, headers=auth)
    assert response.status_code == 200, response.text
    return auth_data, seen, response.json()


def seed_state(dropbox, **overrides):
    state = {
        "access_token": "seeded-access-token",
        "expires_at": time.time() + 3600.0,
        "refresh_token": "seeded-refresh-token",
        "account": "Account Test",
        "remote_path": REMOTE_DEFAULT,
    }
    state.update(overrides)
    dropbox._save_state(state)


def use_local_file(dropbox, path, content=b'{"schema_version": 3, "test": true}'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    dropbox.settings_manager.settings.cloud.local_path = path
    return path


# ---------------------------------------------------------------------------
# Stato e App Key
# ---------------------------------------------------------------------------


def test_status_initially_unconfigured(client, auth, dropbox):
    response = client.get("/api/cloud/dropbox", headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data == {
        "configured": False,
        "connected": False,
        "account": None,
        "last_sync": None,
        "remote_path": REMOTE_DEFAULT,
        "rev": None,
    }


def test_set_key_validates_and_persists(client, auth, dropbox, manager, paths):
    empty = client.put("/api/cloud/dropbox/key", json={"app_key": "   "}, headers=auth)
    assert empty.status_code == 422, empty.text
    assert empty.json()["error"]["code"] == "validation_error"

    data = put_key(client, auth, "  app-key-123  ")
    assert data["configured"] is True
    assert data["connected"] is False
    assert manager.settings.cloud.dropbox.app_key == "app-key-123"
    with open(paths.config_path, "r", encoding="utf-8") as handle:
        persisted = json.load(handle)
    assert persisted["cloud"]["dropbox"]["app_key"] == "app-key-123"


def test_authorize_requires_app_key(client, auth, dropbox):
    response = client.post("/api/cloud/dropbox/authorize", headers=auth)
    assert response.status_code == 400, response.text
    payload = response.json()["error"]
    assert payload["code"] == "dropbox_not_configured"
    assert "App Key" in payload["message"]


def test_authorize_builds_pkce_url(client, auth, dropbox):
    put_key(client, auth, "my-app-key")
    data = authorize(client, auth)
    query = auth_query(data["auth_url"])
    assert query["client_id"] == ["my-app-key"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["token_access_type"] == ["offline"]
    challenge = query["code_challenge"][0]
    assert 43 <= len(challenge) <= 128
    assert "=" not in challenge
    assert data["expires_in_s"] == 600


# ---------------------------------------------------------------------------
# OAuth completo / errori
# ---------------------------------------------------------------------------


def test_complete_saves_tokens_and_account(client, auth, dropbox, http, manager, paths):
    auth_data, seen, status = connect(client, auth, http, account="Mario Rossi")
    challenge = auth_query(auth_data["auth_url"])["code_challenge"][0]
    # Il verifier usato nel token exchange deve corrispondere alla challenge S256.
    assert code_challenge(seen["verifier"]) == challenge
    assert len(seen["verifier"]) >= 43
    assert status["connected"] is True
    assert status["account"] == "Mario Rossi"

    token_call = http.calls[0]
    assert token_call.url == TOKEN_URL
    assert token_call.method == "POST"
    assert isinstance(token_call.data, dict)
    assert token_call.data["grant_type"] == "authorization_code"
    assert token_call.data["code"] == "auth-code-123"
    assert token_call.data["client_id"] == "test-app-key"
    assert token_call.timeout == 15.0

    account_call = http.calls[1]
    assert account_call.url == URL_ACCOUNT
    assert account_call.headers["Authorization"] == "Bearer access-token-1"

    with open(paths.dropbox_state_path, "r", encoding="utf-8") as handle:
        state = json.load(handle)
    assert state["refresh_token"] == "refresh-token-1"
    assert state["account"] == "Mario Rossi"
    assert state["access_token"] == "access-token-1"

    status_response = client.get("/api/cloud/dropbox", headers=auth)
    assert status_response.status_code == 200
    assert status_response.json()["connected"] is True
    assert http.queue == []


def test_complete_is_single_use_and_requires_authorize(client, auth, dropbox, http):
    put_key(client, auth)
    response = client.post(CHECK_COMPLETE, json={"code": "abc"}, headers=auth)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "dropbox_invalid_code"

    authorize(client, auth)
    queue_connect(http)
    first = client.post(CHECK_COMPLETE, json={"code": "abc"}, headers=auth)
    assert first.status_code == 200, first.text
    second = client.post(CHECK_COMPLETE, json={"code": "abc"}, headers=auth)
    assert second.status_code == 400, second.text
    assert second.json()["error"]["code"] == "dropbox_invalid_code"


def test_complete_empty_code(client, auth, dropbox):
    put_key(client, auth)
    response = client.post(CHECK_COMPLETE, json={"code": "  "}, headers=auth)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "dropbox_invalid_code"


def test_invalid_client_maps_to_actionable_message(client, auth, dropbox, http):
    put_key(client, auth)
    authorize(client, auth)
    http.expect(
        lambda call: json_error(
            400, {"error": "invalid_client", "error_description": "bad app key"}
        )
    )
    response = client.post(CHECK_COMPLETE, json={"code": "abc"}, headers=auth)
    assert response.status_code == 400, response.text
    payload = response.json()["error"]
    assert payload["code"] == "dropbox_invalid_client"
    assert "Scoped App" in payload["message"]
    assert "App Key" in payload["message"]


def test_invalid_grant_maps_to_dropbox_invalid_code(client, auth, dropbox, http):
    put_key(client, auth)
    authorize(client, auth)
    http.expect(lambda call: json_error(400, {"error": "invalid_grant"}))
    response = client.post(CHECK_COMPLETE, json={"code": "scaduto"}, headers=auth)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "dropbox_invalid_code"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def _metadata_args(call):
    return json.loads(call.data.decode("utf-8"))


def test_upload_success(client, auth, dropbox, http, tmp_path):
    connect(client, auth, http)
    local_file = use_local_file(dropbox, str(tmp_path / "locale" / "config.json"))
    seen = {}

    def metadata_handler(call):
        seen["metadata_path"] = _metadata_args(call)["path"]
        return json_error(
            409,
            {
                "error_summary": "path/not_found/...",
                "error": {".tag": "path", "path": {".tag": "not_found"}},
            },
        )

    def upload_handler(call):
        seen["upload_args"] = json.loads(call.headers["Dropbox-API-Arg"])
        seen["upload_data"] = call.data
        seen["auth"] = call.headers["Authorization"]
        seen["content_type"] = call.headers["Content-Type"]
        return json_ok({"rev": "rev-1", "size": len(call.data), "name": "config.json"})

    http.expect(metadata_handler)
    http.expect(upload_handler)
    response = client.post("/api/cloud/dropbox/upload", json={"force": False}, headers=auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["rev"] == "rev-1"
    assert "Dropbox" in payload["message"]
    assert seen["metadata_path"] == REMOTE_DEFAULT
    assert seen["upload_args"]["path"] == REMOTE_DEFAULT
    assert seen["upload_args"]["mode"] == "overwrite"
    assert seen["upload_args"]["autorename"] is False
    assert seen["upload_data"] == open(local_file, "rb").read()
    assert seen["auth"] == "Bearer access-token-1"
    assert seen["content_type"] == "application/octet-stream"
    status = client.get("/api/cloud/dropbox", headers=auth).json()
    assert status["rev"] == "rev-1"
    assert status["last_sync"] is not None


def test_upload_conflict_then_force(client, auth, dropbox, http, tmp_path):
    connect(client, auth, http)
    use_local_file(dropbox, str(tmp_path / "config.json"))
    seed_state(dropbox, rev="old-rev")

    http.expect(lambda call: json_ok({"rev": "new-rev", "path": REMOTE_DEFAULT}))
    conflict = client.post("/api/cloud/dropbox/upload", json={"force": False}, headers=auth)
    assert conflict.status_code == 409, conflict.text
    error = conflict.json()["error"]
    assert error["code"] == "dropbox_conflict"
    assert error["params"]["remote_rev"] == "new-rev"

    # Con force il check remoto viene saltato: basta la risposta di upload.
    http.expect(lambda call: json_ok({"rev": "rev-forced"}))
    forced = client.post("/api/cloud/dropbox/upload", json={"force": True}, headers=auth)
    assert forced.status_code == 200, forced.text
    assert forced.json()["rev"] == "rev-forced"
    assert http.queue == []


def test_upload_missing_local_file(client, auth, dropbox, http, tmp_path):
    seed_state(dropbox)
    dropbox.settings_manager.settings.cloud.local_path = str(tmp_path / "manca.json")
    response = client.post("/api/cloud/dropbox/upload", json={}, headers=auth)
    assert response.status_code == 404, response.text
    payload = response.json()["error"]
    assert payload["code"] == "input_missing"
    assert "manca.json" in payload["detail"] or "manca.json" in payload["message"]
    assert http.calls == []


def test_expired_access_token_is_refreshed(client, auth, dropbox, http, tmp_path):
    put_key(client, auth)
    seed_state(
        dropbox,
        access_token="vecchio",
        expires_at=time.time() - 10.0,
        refresh_token="refresh-token-xyz",
    )
    use_local_file(dropbox, str(tmp_path / "config.json"))
    refreshed = {}

    def refresh_handler(call):
        refreshed["form"] = dict(call.data or {})
        return json_ok(token_payload(access="nuovo-token", refresh="refresh-token-xyz"))

    http.expect(refresh_handler)
    http.expect(lambda call: json_error(409, {"error_summary": "path/not_found/"}))
    http.expect(lambda call: json_ok({"rev": "rev-refresh"}))
    response = client.post("/api/cloud/dropbox/upload", json={}, headers=auth)
    assert response.status_code == 200, response.text
    assert refreshed["form"] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token-xyz",
        "client_id": "test-app-key",
    }
    with open(dropbox.state_path, "r", encoding="utf-8") as handle:
        state = json.load(handle)
    assert state["access_token"] == "nuovo-token"


def test_upload_retries_on_429_and_5xx(client, auth, dropbox, http, tmp_path):
    connect(client, auth, http)
    use_local_file(dropbox, str(tmp_path / "config.json"))
    http.expect(lambda call: FakeResponse(429, b"", {"Retry-After": "0"}))
    http.expect(lambda call: FakeResponse(503, b""))
    http.expect(lambda call: json_ok({"rev": "rev-retry"}))
    http.expect(lambda call: json_ok({"rev": "rev-upload"}))
    response = client.post("/api/cloud/dropbox/upload", json={}, headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["rev"] == "rev-upload"
    # 429 (Retry-After 0) + 503 (backoff 1s)
    assert len(http.sleeps) == 2
    assert http.sleeps[0] == 0.0
    assert http.sleeps[1] == 1.0


def test_network_error_maps_to_network_error(client, auth, dropbox, http, tmp_path):
    connect(client, auth, http)
    use_local_file(dropbox, str(tmp_path / "config.json"))

    def boom(call):
        raise requests.ConnectionError("rete assente")

    http.expect(boom)
    response = client.post("/api/cloud/dropbox/upload", json={}, headers=auth)
    assert response.status_code == 502, response.text
    payload = response.json()["error"]
    assert payload["code"] == "network_error"
    assert "connessione" in payload["message"].lower()


def test_upload_server_error_maps_to_cloud_error(client, auth, dropbox, http, tmp_path):
    connect(client, auth, http)
    use_local_file(dropbox, str(tmp_path / "config.json"))
    http.expect(lambda call: json_error(409, {"error_summary": "path/not_found/"}))
    http.expect(lambda call: json_error(400, {"error_summary": "malformed_path/..."}))
    response = client.post("/api/cloud/dropbox/upload", json={}, headers=auth)
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "cloud_error"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def test_download_writes_file_and_tracks_rev(client, auth, dropbox, http, tmp_path):
    seed_state(dropbox, rev="remote-rev-0")
    local_file = str(tmp_path / "scaricata" / "config.json")
    dropbox.settings_manager.settings.cloud.local_path = local_file
    remote_content = b'{"schema_version": 3, "cloud": true}'

    def download_response(call):
        return FakeResponse(
            200,
            remote_content,
            {"Dropbox-API-Result": json.dumps({"rev": "remote-rev-1", "size": len(remote_content)})},
        )

    http.expect(download_response)
    response = client.post("/api/cloud/dropbox/download", json={"force": False}, headers=auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["changed"] is True
    with open(local_file, "rb") as handle:
        assert handle.read() == remote_content
    download_call = http.calls[0]
    assert json.loads(download_call.headers["Dropbox-API-Arg"])["path"] == REMOTE_DEFAULT
    assert download_call.headers["Authorization"] == "Bearer seeded-access-token"
    state = json.loads(open(dropbox.state_path, "r", encoding="utf-8").read())
    assert state["rev"] == "remote-rev-1"
    assert state["last_sync"] is not None

    http.expect(download_response)
    second = client.post("/api/cloud/dropbox/download", json={}, headers=auth)
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False


def _download_response(content: bytes, rev: str) -> FakeResponse:
    return FakeResponse(
        200,
        content,
        {"Dropbox-API-Result": json.dumps({"rev": rev, "size": len(content)})},
    )


def test_download_conflict_when_both_sides_changed(client, auth, dropbox, http, tmp_path):
    local_content = b'{"locale": "modificato"}'
    remote_content = b'{"remoto": true}'
    local_file = str(tmp_path / "config.json")
    with open(local_file, "wb") as handle:
        handle.write(local_content)
    dropbox.settings_manager.settings.cloud.local_path = local_file
    seed_state(
        dropbox,
        rev="rev-1",
        local_sha256=hashlib.sha256(b'{"locale": "originale"}').hexdigest(),
    )

    http.expect(lambda call: _download_response(remote_content, "rev-2"))
    conflict = client.post("/api/cloud/dropbox/download", json={"force": False}, headers=auth)
    assert conflict.status_code == 409, conflict.text
    payload = conflict.json()["error"]
    assert payload["code"] == "dropbox_conflict"
    assert payload["params"]["remote_rev"] == "rev-2"
    with open(local_file, "rb") as handle:
        assert handle.read() == local_content

    http.expect(lambda call: _download_response(remote_content, "rev-2"))
    forced = client.post("/api/cloud/dropbox/download", json={"force": True}, headers=auth)
    assert forced.status_code == 200, forced.text
    assert forced.json()["changed"] is True
    with open(local_file, "rb") as handle:
        assert handle.read() == remote_content


def test_download_preserves_local_changes_when_remote_unchanged(
    client, auth, dropbox, http, tmp_path
):
    local_content = b'{"locale": "modificato"}'
    local_file = str(tmp_path / "config.json")
    with open(local_file, "wb") as handle:
        handle.write(local_content)
    dropbox.settings_manager.settings.cloud.local_path = local_file
    seed_state(
        dropbox,
        rev="rev-1",
        local_sha256=hashlib.sha256(b'{"locale": "originale"}').hexdigest(),
    )
    http.expect(lambda call: _download_response(b'{"remoto": true}', "rev-1"))
    response = client.post("/api/cloud/dropbox/download", json={}, headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is False
    with open(local_file, "rb") as handle:
        assert handle.read() == local_content


def test_download_missing_remote_file(client, auth, dropbox, http, tmp_path):
    seed_state(dropbox)
    dropbox.settings_manager.settings.cloud.local_path = str(tmp_path / "config.json")
    http.expect(
        lambda call: json_error(
            409,
            {
                "error_summary": "path/not_found/...",
                "error": {".tag": "path", "path": {".tag": "not_found"}},
            },
        )
    )
    response = client.post("/api/cloud/dropbox/download", json={}, headers=auth)
    assert response.status_code == 404, response.text
    payload = response.json()["error"]
    assert payload["code"] == "not_found"
    assert "remoto" in payload["message"].lower()


def test_download_requires_connection(client, auth, dropbox):
    response = client.post("/api/cloud/dropbox/download", json={}, headers=auth)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "dropbox_not_configured"


# ---------------------------------------------------------------------------
# Disconnessione
# ---------------------------------------------------------------------------


def test_disconnect_removes_tokens_but_keeps_key(client, auth, dropbox, http, paths):
    connect(client, auth, http)
    response = client.delete("/api/cloud/dropbox", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}

    status = client.get("/api/cloud/dropbox", headers=auth).json()
    assert status["configured"] is True
    assert status["connected"] is False
    assert status["account"] is None

    with open(paths.dropbox_state_path, "r", encoding="utf-8") as handle:
        state = json.load(handle)
    assert "refresh_token" not in state
    assert "access_token" not in state
    with open(paths.config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    assert config["cloud"]["dropbox"]["app_key"] == "test-app-key"


def test_changing_app_key_drops_old_tokens(client, auth, dropbox):
    put_key(client, auth, "prima-app-key")
    seed_state(dropbox)
    assert client.get("/api/cloud/dropbox", headers=auth).json()["connected"] is True
    put_key(client, auth, "seconda-app-key")
    status = client.get("/api/cloud/dropbox", headers=auth).json()
    assert status["configured"] is True
    assert status["connected"] is False
    assert dropbox._load_state().get("refresh_token") is None


# ---------------------------------------------------------------------------
# Helper di PKCE
# ---------------------------------------------------------------------------


def test_pkce_helpers_are_valid():
    verifier = generate_code_verifier()
    assert 43 <= len(verifier) <= 128
    assert all(char.isalnum() or char in "-._~" for char in verifier)
    challenge = code_challenge(verifier)
    assert 43 <= len(challenge) <= 128
    assert "=" not in challenge


def test_tokens_and_codes_are_never_logged(client, auth, dropbox, http, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        connect(client, auth, http)
        client.get("/api/cloud/dropbox", headers=auth)
        client.post(CHECK_COMPLETE, json={"code": "codice-rifiutato"}, headers=auth)
    for secret in ("access-token-1", "refresh-token-1", "auth-code-123", "codice-rifiutato"):
        assert secret not in caplog.text

