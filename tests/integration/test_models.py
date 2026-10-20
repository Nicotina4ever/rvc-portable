"""Test di integrazione per le rotte modelli (scan mockato + scan reale base)."""

from __future__ import annotations

import os

import pytest

from app.core import model_scan

pytestmark = pytest.mark.integration


def _entry(path: str, name: str = "voce") -> dict:
    return {
        "name": name,
        "path": path,
        "index_path": "",
        "size_mb": 57.6,
        "version_guess": "v2",
        "source": "Modelli",
        "has_index": False,
        "warnings": ["indice opzionale assente"],
        "mtime": 1.0,
    }


def test_list_models_default_root(client, auth, paths, manager, monkeypatch):
    recorded = {}

    def fake_scan(roots, default_index_hint=""):
        recorded["roots"] = list(roots)
        recorded["hint"] = default_index_hint
        model_path = os.path.join(roots[0], "Nicola.pth")
        return {"roots": list(roots), "models": [_entry(model_path)], "warnings": ["un avviso"]}

    hint = os.path.join(paths.data_dir, "indice.index")
    manager.settings.audio.index_path = hint
    monkeypatch.setattr(model_scan, "scan_models", fake_scan)

    response = client.get("/api/models", headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["roots"] == [paths.models_dir]
    assert recorded["roots"] == [paths.models_dir]
    assert recorded["hint"] == hint
    assert len(data["models"]) == 1
    assert data["models"][0]["name"] == "voce"
    assert data["warnings"] == ["un avviso"]


def test_scan_models_with_explicit_roots(client, auth, tmp_path, monkeypatch):
    root = tmp_path / "modelli-custom"
    root.mkdir()
    recorded = {}

    def fake_scan(roots, default_index_hint=""):
        recorded["roots"] = list(roots)
        return {"roots": list(roots), "models": [_entry(os.path.join(roots[0], "x.pth"))], "warnings": []}

    monkeypatch.setattr(model_scan, "scan_models", fake_scan)
    response = client.post("/api/models/scan", json={"roots": [str(root)]}, headers=auth)
    assert response.status_code == 200, response.text
    assert recorded["roots"] == [os.path.abspath(str(root))]
    assert response.json()["roots"] == [os.path.abspath(str(root))]


def test_scan_models_without_body_uses_default(client, auth, paths, monkeypatch):
    recorded = {}

    def fake_scan(roots, default_index_hint=""):
        recorded["roots"] = list(roots)
        return {"roots": list(roots), "models": [], "warnings": []}

    monkeypatch.setattr(model_scan, "scan_models", fake_scan)
    response = client.post("/api/models/scan", headers=auth)
    assert response.status_code == 200, response.text
    assert recorded["roots"] == [paths.models_dir]


def test_scan_models_missing_root_is_validation_error(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(
        model_scan,
        "scan_models",
        lambda roots, default_index_hint="": {"roots": list(roots), "models": [], "warnings": []},
    )
    missing = str(tmp_path / "non-esiste")
    response = client.post("/api/models/scan", json={"roots": [missing]}, headers=auth)
    assert response.status_code == 422, response.text
    payload = response.json()["error"]
    assert payload["code"] == "validation_error"
    assert "non-esiste" in payload["message"]

    invalid = client.post("/api/models/scan", json={"roots": "non-una-lista"}, headers=auth)
    assert invalid.status_code == 422, invalid.text


def test_scan_models_missing_default_root_returns_warning(client, auth, paths):
    os.rmdir(paths.models_dir)
    response = client.get("/api/models", headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["roots"] == []
    assert data["models"] == []
    assert data["warnings"]
    assert paths.models_dir in data["warnings"][0]


def test_scan_not_implemented_is_503_model_invalid(client, auth, monkeypatch):
    def not_ready(roots, default_index_hint=""):
        raise NotImplementedError("in arrivo")

    monkeypatch.setattr(model_scan, "scan_models", not_ready)
    for response in (
        client.get("/api/models", headers=auth),
        client.post("/api/models/scan", json={}, headers=auth),
    ):
        assert response.status_code == 503, response.text
        payload = response.json()["error"]
        assert payload["code"] == "model_invalid"
        assert "non ancora disponibile" in payload["message"]


def test_probe_returns_matching_entries(client, auth, tmp_path, monkeypatch):
    model_file = tmp_path / "voce.pth"
    model_file.write_bytes(b"dummy-model")
    recorded = {}

    def fake_scan(roots, default_index_hint=""):
        recorded["roots"] = list(roots)
        return {
            "roots": list(roots),
            "models": [_entry(str(model_file), name="voce")],
            "warnings": [],
        }

    monkeypatch.setattr(model_scan, "scan_models", fake_scan)
    response = client.post("/api/models/probe", json={"paths": [str(model_file)]}, headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["models"]) == 1
    assert data["models"][0]["path"] == str(model_file)
    assert recorded["roots"] == [os.path.dirname(str(model_file))]


def test_probe_missing_file_is_404(client, auth, tmp_path):
    missing = str(tmp_path / "manca.pth")
    response = client.post("/api/models/probe", json={"paths": [missing]}, headers=auth)
    assert response.status_code == 404, response.text
    payload = response.json()["error"]
    assert payload["code"] == "model_not_found"
    assert "manca.pth" in payload["message"]


def test_probe_requires_paths(client, auth):
    for body in ({}, {"paths": []}, {"paths": [""]}):
        response = client.post("/api/models/probe", json=body, headers=auth)
        assert response.status_code == 422, (body, response.text)
        assert response.json()["error"]["code"] == "validation_error"


def test_probe_fallback_entry_when_scan_ignores_file(client, auth, tmp_path, monkeypatch):
    model_file = tmp_path / "mio.pth"
    model_file.write_bytes(b"1234")
    monkeypatch.setattr(
        model_scan,
        "scan_models",
        lambda roots, default_index_hint="": {"roots": list(roots), "models": [], "warnings": []},
    )
    response = client.post("/api/models/probe", json={"paths": [str(model_file)]}, headers=auth)
    assert response.status_code == 200, response.text
    entry = response.json()["models"][0]
    assert entry["path"] == str(model_file)
    assert entry["name"] == "mio"
    assert entry["has_index"] is False


def test_real_model_scan_entry_contract(client, auth, paths):
    """Verifica il contratto ModelEntry con la scansione reale del motore."""
    model_file = os.path.join(paths.models_dir, "voce-integrazione.pth")
    with open(model_file, "wb") as handle:
        handle.write(b"dummy")
    index_file = os.path.join(paths.models_dir, "added_voce-integrazione.index")
    with open(index_file, "wb") as handle:
        handle.write(b"dummy")
    try:
        response = client.get("/api/models", headers=auth)
        assert response.status_code == 200, response.text
        data = response.json()
        matching = [entry for entry in data["models"] if entry["path"] == model_file]
        assert matching, data
        entry = matching[0]
        for key in (
            "name",
            "path",
            "index_path",
            "size_mb",
            "version_guess",
            "source",
            "has_index",
            "warnings",
            "mtime",
        ):
            assert key in entry, (key, entry)
        assert entry["name"] == "voce-integrazione"
    finally:
        for path in (model_file, index_file):
            try:
                os.remove(path)
            except OSError:
                pass
