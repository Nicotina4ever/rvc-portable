"""Test di ``app.core.engine_rvc`` con un worker finto (nessun torch/CUDA).

Il worker vero e' coperto da ``tests/e2e/run_real_conversion.py``; qui si
verifica il protocollo, la gestione del ciclo di vita, il cancel e il
riavvio automatico dopo un crash del worker.
"""

from __future__ import annotations

import math
import os
import sys
import time
import wave

import pytest

from app.core import devices
from app.core.engine import EngineError, InferParams, NullEngine, pcm_peak_amplitude
from app.core.engine_rvc import (
    RvcEngine,
    _normalize_effective_device,
    _normalize_requested_device,
    create_engine,
)

FAKE_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_worker.py")


def _write_wav(path, seconds: float = 0.2, sample_rate: int = 16000):
    frames = int(seconds * sample_rate)
    payload = bytearray()
    for index in range(frames):
        value = int(9000 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
        payload += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return str(path)


@pytest.fixture()
def fake_probe(monkeypatch):
    probe = devices.RuntimeProbe(
        available=True,
        python_executable=sys.executable,
        python_version="3.9.13",
        torch="2.0.0+cu118",
        cuda=False,
        mps=False,
        engine_ok=True,
        fairseq_ok=True,
        base_models={"hubert_base.pt": 1, "rmvpe.pt": 1},
    )
    monkeypatch.setattr(
        devices, "probe_engine", lambda *args, **kwargs: probe
    )
    return probe


@pytest.fixture()
def engine(paths, manager, fake_probe):
    instance = RvcEngine(
        paths,
        manager,
        python_executable=sys.executable,
        worker_command=[sys.executable, "-B", FAKE_WORKER],
    )
    if not instance.status().available:
        instance.shutdown()
        pytest.skip("rvc_python non presente nell'interprete che esegue i test")
    try:
        yield instance
    finally:
        instance.shutdown()


@pytest.fixture()
def model_file(tmp_path):
    path = tmp_path / "voce.pth"
    path.write_bytes(b"dummy-model")
    return str(path)


def test_load_infer_unload_roundtrip(engine, model_file, tmp_path):
    output = tmp_path / "output.wav"
    stages = []
    logs = []
    engine.load(model_file, "", version="v2", device="cpu")
    status = engine.status()
    assert status.available is True
    assert status.loaded is True
    assert status.warm is True
    assert status.device == "cpu"
    assert status.model_path == os.path.abspath(model_file)

    result = engine.infer(
        _write_wav(tmp_path / "input.wav"),
        str(output),
        InferParams(),
        on_log=logs.append,
        on_stage=lambda name, progress: stages.append(name),
    )
    assert result.ok is True, result.to_dict()
    assert os.path.isfile(output)
    assert pcm_peak_amplitude(str(output)) > 0.05
    assert result.sample_rate == 16000
    assert result.duration_s > 0
    assert "extract" in stages and "f0" in stages and "write" in stages
    assert logs

    engine.unload()
    assert engine.status().loaded is False
    # Dopo unload il motore ricarica il modello desiderato al prossimo infer.
    again = engine.infer(
        _write_wav(tmp_path / "input2.wav"), str(tmp_path / "out2.wav"), InferParams()
    )
    assert again.ok is True, again.to_dict()


def test_infer_without_load_raises(engine, tmp_path):
    with pytest.raises(EngineError) as excinfo:
        engine.infer(
            _write_wav(tmp_path / "input.wav"),
            str(tmp_path / "out.wav"),
            InferParams(),
        )
    assert excinfo.value.code == "engine_unavailable"


def test_missing_input_raises(engine, model_file, tmp_path):
    engine.load(model_file, device="cpu")
    with pytest.raises(EngineError) as excinfo:
        engine.infer(
            str(tmp_path / "non-esiste.wav"), str(tmp_path / "out.wav"), InferParams()
        )
    assert excinfo.value.code == "input_missing"


def test_load_missing_model_raises(engine, tmp_path):
    with pytest.raises(EngineError) as excinfo:
        engine.load(str(tmp_path / "non-esiste.pth"), device="cpu")
    assert excinfo.value.code == "model_invalid"


def test_cancel_is_cooperative(engine, model_file, tmp_path):
    engine.load(model_file, device="cpu")
    started = time.time()

    def is_cancelled() -> bool:
        return (time.time() - started) > 0.15

    result = engine.infer(
        _write_wav(tmp_path / "input.wav"),
        str(tmp_path / "out.wav"),
        InferParams(),
        is_cancelled=is_cancelled,
    )
    assert result.ok is False
    assert result.error_code == "canceled"


def test_worker_crash_is_recovered(engine, model_file, tmp_path):
    engine.load(model_file, device="cpu")
    proc = engine._proc  # noqa: SLF001 - test di resilienza
    assert proc is not None
    proc.kill()
    proc.wait(timeout=5.0)
    result = engine.infer(
        _write_wav(tmp_path / "input.wav"),
        str(tmp_path / "recovered.wav"),
        InferParams(),
    )
    assert result.ok is True, result.to_dict()
    assert os.path.isfile(str(tmp_path / "recovered.wav"))
    assert engine.status().loaded is True


def test_status_unavailable_without_runtime(paths, manager, tmp_path):
    missing = str(tmp_path / "non-esiste" / "python.exe")
    instance = RvcEngine(paths, manager, python_executable=missing)
    try:
        status = instance.status()
        assert status.available is False
        assert status.code == "engine_unavailable"
        with pytest.raises(EngineError):
            instance.load(str(tmp_path / "voce.pth"))
    finally:
        instance.shutdown()


def test_create_engine_returns_null_without_runtime(tmp_path):
    from app.paths import AppPaths

    app_paths = AppPaths(
        app_root=str(tmp_path), data_dir=str(tmp_path / "data"), portable=True
    )
    app_paths.ensure()
    assert app_paths.runtime_python is None
    instance = create_engine(app_paths)
    assert isinstance(instance, NullEngine)
    assert instance.status().available is False


@pytest.mark.parametrize(
    "requested,expected",
    [
        ("", "auto"),
        ("auto", "auto"),
        ("cuda", "cuda:0"),
        ("cuda:", "cuda:0"),
        ("cuda:1", "cuda:1"),
        ("CUDA:2", "cuda:2"),
        ("dml:0", "cpu"),
        ("cpu:", "cpu"),
        ("mps", "mps"),
        ("boh", "cpu"),
    ],
)
def test_normalize_requested_device(requested, expected):
    assert _normalize_requested_device(requested) == expected


@pytest.mark.parametrize(
    "device,expected",
    [("cuda", "cuda:0"), ("cuda:1", "cuda:1"), ("cpu:", "cpu"), ("dml:0", "cpu"), ("mps", "mps")],
)
def test_normalize_effective_device(device, expected):
    assert _normalize_effective_device(device) == expected
