"""Test di integrazione delle rotte del ponte Android/Dropbox."""

from __future__ import annotations

import json
import os


def _shared(tmp_path):
    return str(tmp_path / "Dropbox" / "TestRVC")


def test_status_and_detect(client, auth):
    status = client.get("/api/android", headers=auth)
    assert status.status_code == 200
    data = status.json()
    assert "roots" in data
    assert "paths" in data
    assert data["enabled"] is False

    detect = client.post("/api/android/detect", headers=auth)
    assert detect.status_code == 200
    payload = detect.json()
    assert isinstance(payload["roots"], list)
    assert "suggested_shared_dir" in payload


def test_preset_creates_structure_and_updates_settings(client, auth, tmp_path, watcher):
    shared = _shared(tmp_path)
    try:
        response = client.post("/api/android/preset", json={"shared_dir": shared}, headers=auth)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert os.path.isdir(os.path.join(shared, "AudioIn"))
        assert os.path.isdir(os.path.join(shared, "AudioOut"))
        assert os.path.isfile(os.path.join(shared, "config.json"))
        assert os.path.isfile(os.path.join(shared, "modelli.txt"))

        settings = client.get("/api/settings", headers=auth).json()["settings"]
        assert settings["android"]["enabled"] is True
        assert settings["android"]["shared_dir"] == shared
        assert settings["audio"]["input_dir"] == os.path.join(shared, "AudioIn")
        assert settings["audio"]["output_dir"] == os.path.join(shared, "AudioOut")
        assert settings["cloud"]["hot_reload"] is True
        assert watcher.status().get("running") is True
    finally:
        client.post("/api/monitor/stop", headers=auth)


def test_import_flat_config_updates_audio(client, auth, tmp_path):
    shared = str(tmp_path / "shared")
    os.makedirs(shared)
    patch = {
        "patch": {
            "android": {"enabled": True, "shared_dir": shared},
        }
    }
    assert client.patch("/api/settings", json=patch, headers=auth).status_code == 200
    model = tmp_path / "voice.pth"
    model.write_bytes(b"model")
    config = {
        "model_path": str(model),
        "pitch": 4,
        "method": "harvest",
        "protect": 0.2,
        "index_rate": 0.5,
    }
    with open(os.path.join(shared, "config.json"), "w", encoding="utf-8") as handle:
        json.dump(config, handle)
    response = client.post("/api/android/import", headers=auth)
    assert response.status_code == 200, response.text
    assert "pitch" in response.json()["result"]["applied"]
    settings = client.get("/api/settings", headers=auth).json()["settings"]
    assert settings["audio"]["pitch"] == 4
    assert settings["audio"]["method"] == "harvest"


def test_put_flat_config_payload(client, auth):
    response = client.put("/api/android/config", json={"pitch": -3, "method": "pm"}, headers=auth)
    assert response.status_code == 200, response.text
    applied = response.json()["result"]["applied"]
    assert "pitch" in applied and "method" in applied
    settings = client.get("/api/settings", headers=auth).json()["settings"]
    assert settings["audio"]["pitch"] == -3
    assert settings["audio"]["method"] == "pm"


def test_import_missing_config_returns_404(client, auth, tmp_path):
    shared = str(tmp_path / "empty")
    os.makedirs(shared)
    client.patch(
        "/api/settings",
        json={"patch": {"android": {"enabled": True, "shared_dir": shared}}},
        headers=auth,
    )
    config_path = os.path.join(shared, "config.json")
    if os.path.isfile(config_path):
        os.remove(config_path)  # il salvataggio impostazioni esporta il config ibrido
    response = client.post("/api/android/import", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "android_config_missing"


def test_sync_rewrites_files(client, auth, tmp_path):
    shared = str(tmp_path / "sync")
    client.patch(
        "/api/settings",
        json={"patch": {"android": {"enabled": True, "shared_dir": shared}}},
        headers=auth,
    )
    response = client.post("/api/android/sync", headers=auth)
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert os.path.isfile(summary["config_path"])
    assert os.path.isfile(summary["models_path"])


def test_android_requires_token(client):
    assert client.get("/api/android").status_code == 401


def test_preset_without_dropbox_and_empty_dir(client, auth, monkeypatch):
    monkeypatch.setattr("app.android_bridge.detect_dropbox_roots", lambda: [])
    response = client.post("/api/android/preset", json={"shared_dir": ""}, headers=auth)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "android_dropbox_missing"
