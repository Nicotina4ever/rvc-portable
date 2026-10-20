"""Test di integrazione per meta, diagnostica e spegnimento."""

from __future__ import annotations

import sys
import threading

import pytest

from app import __version__, doctor

pytestmark = pytest.mark.integration


def test_meta_contract(client, auth, paths):
    response = client.get("/api/meta", headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["version"] == __version__
    assert data["app"] == "RVC Portable"
    assert data["python"] == sys.version
    assert data["platform"]
    assert data["paths"]["data_dir"] == paths.data_dir
    assert data["paths"]["models_dir"] == paths.models_dir
    assert data["engine"]["available"] is True
    assert data["engine"]["device"] == "fake"
    assert isinstance(data["started_at"], float)
    assert data["uptime_s"] >= 0.0


def test_meta_works_without_engine_status(client, auth, app):
    class BrokenEngine:
        def status(self):
            raise RuntimeError("motore rotto")

        def shutdown(self):
            pass

    original = app.state.engine
    app.state.engine = BrokenEngine()
    try:
        response = client.get("/api/meta", headers=auth)
    finally:
        app.state.engine = original
    assert response.status_code == 200, response.text
    assert response.json()["engine"]["available"] is False


def test_diagnostics_uses_doctor(client, auth, monkeypatch):
    calls = []

    def fake_run_checks(paths, settings, force_probe=False, probe=None):
        calls.append({"paths": paths.data_dir, "force": force_probe})
        return {
            "overall": "ok",
            "counts": {"ok": 1, "warn": 0, "fail": 0, "info": 0},
            "checks": [{"id": "fake", "label": "Fake", "status": "ok"}],
            "environment": {"platform": "test"},
        }

    monkeypatch.setattr(doctor, "run_checks", fake_run_checks)
    response = client.get("/api/system/diagnostics", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["overall"] == "ok"
    assert calls[-1]["force"] is False
    assert calls[-1]["paths"]

    forced = client.get("/api/system/diagnostics?force=true", headers=auth)
    assert forced.status_code == 200, forced.text
    assert calls[-1]["force"] is True


def test_shutdown_calls_launcher_callback(client, auth, app):
    event = threading.Event()
    app.state.shutdown_callback = event.set
    response = client.post("/api/system/shutdown", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    assert event.wait(3.0), "callback di spegnimento non invocata"


def test_shutdown_without_callback_is_503(client, auth, app):
    app.state.shutdown_callback = None
    response = client.post("/api/system/shutdown", headers=auth)
    assert response.status_code == 503, response.text
    payload = response.json()["error"]
    assert payload["code"] == "engine_unavailable"
    assert "launcher" in payload["message"].lower()
