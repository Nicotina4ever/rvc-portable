"""Test della diagnostica con probe sintetico (nessun torch richiesto)."""

from __future__ import annotations

import sys

import app.doctor as doctor
from app.core.devices import RuntimeProbe


def good_probe() -> RuntimeProbe:
    return RuntimeProbe(
        available=True,
        python_executable=sys.executable,
        python_version="3.9.13",
        torch="2.0.0+cu118",
        cuda=True,
        gpu_name="NVIDIA RTX",
        vram_gb=8.0,
        engine_ok=True,
        fairseq_ok=True,
        base_models_dir="runtime/base_model",
        base_models={"hubert_base.pt": 200 * 1024 * 1024, "rmvpe.pt": 200 * 1024 * 1024},
        base_models_missing=[],
    )


def prepare(manager, tmp_path, model_file):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html></html>", encoding="utf-8")
    manager.load()
    manager.settings.audio.input_dir = str(input_dir)
    manager.settings.audio.output_dir = str(output_dir)
    manager.settings.audio.model_path = model_file
    manager.save()


def test_all_good(manager, paths, tmp_path, model_file, monkeypatch):
    prepare(manager, tmp_path, model_file)
    monkeypatch.setattr(doctor.devices, "probe_engine", lambda paths, force=False: good_probe())
    report = doctor.run_checks(paths, manager.settings, force_probe=True)
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["engine"]["status"] == "ok"
    assert checks["fairseq"]["status"] == "ok"
    assert checks["torch"]["status"] == "ok"
    assert checks["cuda"]["status"] == "ok"
    assert checks["base_models"]["status"] == "ok"
    assert checks["paths"]["status"] == "ok"
    assert report["overall"] == "ok", report["checks"]


def test_new_torch_fails(manager, paths, tmp_path, model_file, monkeypatch):
    prepare(manager, tmp_path, model_file)
    probe = good_probe()
    probe.torch = "2.7.1+cu118"
    monkeypatch.setattr(doctor.devices, "probe_engine", lambda paths, force=False: probe)
    report = doctor.run_checks(paths, manager.settings, force_probe=True)
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["torch"]["status"] == "fail"
    assert report["overall"] == "fail"
    assert doctor.summary_text(report)


def test_missing_engine(manager, paths, tmp_path, model_file, monkeypatch):
    prepare(manager, tmp_path, model_file)
    probe = good_probe()
    probe.engine_ok = False
    probe.fairseq_ok = False
    probe.base_models = {}
    probe.base_models_missing = ["hubert_base.pt", "rmvpe.pt"]
    probe.torch = ""
    probe.cuda = False
    monkeypatch.setattr(doctor.devices, "probe_engine", lambda paths, force=False: probe)
    report = doctor.run_checks(paths, manager.settings, force_probe=True)
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["engine"]["status"] == "fail"
    assert checks["base_models"]["status"] == "fail"
    assert report["counts"]["fail"] >= 2
