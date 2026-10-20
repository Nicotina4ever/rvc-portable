"""Test di integrazione per /api/hardware (probe sempre mockato)."""

from __future__ import annotations

import pytest

from app.core import devices

pytestmark = pytest.mark.integration


def _probe(**overrides) -> devices.RuntimeProbe:
    base = dict(
        available=True,
        python_executable="C:/runtime/python.exe",
        python_version="3.9.13",
        torch="2.0.0+cu118",
        engine_ok=True,
        fairseq_ok=True,
        base_models_dir="C:/runtime/rvc/base_model",
        checked_at=0.0,
    )
    base.update(overrides)
    return devices.RuntimeProbe(**base)


def _patch_probe(monkeypatch, probe):
    calls = []

    def fake_probe(paths, force=False, timeout=180.0):
        calls.append({"paths": paths, "force": force})
        return probe

    monkeypatch.setattr(devices, "probe_engine", fake_probe)
    return calls


def test_hardware_cpu_only(client, auth, monkeypatch, manager):
    calls = _patch_probe(monkeypatch, _probe(cuda=False, mps=False))
    manager.settings.engine.device = "auto"
    response = client.get("/api/hardware", headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert calls and calls[0]["force"] is False
    assert data["probe"]["python_version"] == "3.9.13"
    assert data["probe"]["cuda"] is False
    assert data["system"]["cpu_count"] >= 1
    ids = [device["id"] for device in data["devices"]]
    assert ids == ["auto", "cpu"]
    for device in data["devices"]:
        assert device["label"]
        assert device["available"] is True
        assert device["reason"]
    assert data["effective_device"] == "cpu"
    assert data["requested_device"] == "auto"
    assert data["directml_supported"] is False
    assert any("DirectML" in note for note in data["notes"])


def test_hardware_cuda_and_mps_options(client, auth, monkeypatch, manager):
    probe = _probe(cuda=True, mps=False, gpu_name="NVIDIA RTX 3060", vram_gb=12.0)
    _patch_probe(monkeypatch, probe)
    manager.settings.engine.device = "auto"
    data = client.get("/api/hardware", headers=auth).json()
    ids = [device["id"] for device in data["devices"]]
    assert ids == ["auto", "cpu", "cuda:0"]
    cuda = [device for device in data["devices"] if device["id"] == "cuda:0"][0]
    assert "RTX 3060" in cuda["label"]
    assert "12.0 GB" in cuda["reason"]
    assert data["effective_device"] == "cuda:0"

    probe.mps = True
    data = client.get("/api/hardware", headers=auth).json()
    ids = [device["id"] for device in data["devices"]]
    assert "mps" in ids


def test_hardware_requested_cuda_falls_back(client, auth, monkeypatch, manager):
    probe = _probe(cuda=False, mps=False)
    _patch_probe(monkeypatch, probe)
    manager.settings.engine.device = "cuda:0"
    data = client.get("/api/hardware", headers=auth).json()
    assert data["effective_device"] == "cpu"
    assert any("CUDA non disponibile" in warning for warning in data["warnings"])


def test_hardware_unavailable_probe(client, auth, monkeypatch):
    def broken_probe(paths, force=False, timeout=180.0):
        raise OSError("runtime mancante")

    monkeypatch.setattr(devices, "probe_engine", broken_probe)
    response = client.get("/api/hardware", headers=auth)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "engine_unavailable"
