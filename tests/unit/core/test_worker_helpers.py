"""Test delle utilita' pure di ``app.core.worker`` (senza torch/model)."""

from __future__ import annotations

import os
import wave

import pytest

from app.core.worker import (
    _effective_sample_rate,
    _normalize_params,
    _normalize_requested_device,
    _validate_audio_result,
    write_audio_atomic,
)


@pytest.mark.parametrize(
    "requested,expected",
    [
        ("", "auto"),
        ("auto", "auto"),
        ("cuda", "cuda:0"),
        ("CUDA:1", "cuda:1"),
        ("dml:0", "cpu"),
        ("cpu:", "cpu"),
        ("mps", "mps"),
        ("sconosciuto", "cpu"),
    ],
)
def test_normalize_requested_device(requested, expected):
    assert _normalize_requested_device(requested) == expected


@pytest.mark.parametrize(
    "tgt,resample,expected",
    [
        (48000, 0, 48000),
        (48000, 44100, 44100),
        (40000, 16000, 16000),
        (40000, 48000, 48000),
        (0, 0, 0),
    ],
)
def test_effective_sample_rate(tgt, resample, expected):
    assert _effective_sample_rate(tgt, resample) == expected


def test_normalize_params_fills_defaults_and_coerces():
    params = _normalize_params(
        {
            "pitch": "3",
            "method": "HARVEST",
            "protect": "0.5",
            "index_rate": 0.2,
            "filter_radius": "2",
            "resample_sr": "44100",
            "rms_mix_rate": 0.1,
            "output_format": "FLAC",
            "sconosciuto": 1,
        }
    )
    assert params["pitch"] == 3
    assert params["method"] == "harvest"
    assert params["protect"] == pytest.approx(0.5)
    assert params["filter_radius"] == 2
    assert params["resample_sr"] == 44100
    assert params["output_format"] == "flac"
    assert "sconosciuto" not in params


def test_normalize_params_rejects_unknown_method_and_format():
    params = _normalize_params({"method": "boh", "output_format": "mp3"})
    assert params["method"] == "rmvpe"
    assert params["output_format"] == "wav"
    # None non sovrascrive i default
    assert _normalize_params(None)["method"] == "rmvpe"


def test_validate_audio_result_accepts_ndarray():
    np = pytest.importorskip("numpy")
    array = np.zeros(100, dtype="int16")
    assert _validate_audio_result(array) is array


def test_validate_audio_result_rejects_string_and_tuple():
    from app.core.worker import WorkerError

    with pytest.raises(WorkerError) as string_error:
        _validate_audio_result("traceback di errore")
    assert string_error.value.code == "engine_error"
    assert "traceback" in string_error.value.detail

    with pytest.raises(WorkerError):
        _validate_audio_result(("errore", (None, None)))
    with pytest.raises(WorkerError):
        _validate_audio_result(None)


def test_write_audio_atomic_wav(tmp_path):
    np = pytest.importorskip("numpy")
    samples = (np.sin(np.linspace(0, 40, 1600)) * 20000).astype("int16")
    output = tmp_path / "out.wav"
    write_audio_atomic(str(output), samples, 16000, "wav")
    assert output.is_file()
    with wave.open(str(output), "rb") as handle:
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 1600
    assert not list(tmp_path.glob("*.part-*"))


def test_write_audio_atomic_flac(tmp_path):
    pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    samples = (np.sin(np.linspace(0, 40, 800)) * 15000).astype("int16")
    output = tmp_path / "out.flac"
    write_audio_atomic(str(output), samples, 16000, "flac")
    assert output.is_file()
    import soundfile as sf

    info = sf.info(str(output))
    assert info.samplerate == 16000
    assert info.frames == 800


def test_write_audio_atomic_creates_directory(tmp_path):
    np = pytest.importorskip("numpy")
    samples = np.zeros(10, dtype="int16")
    output = tmp_path / "sub" / "dir" / "out.wav"
    write_audio_atomic(str(output), samples, 8000, "wav")
    assert os.path.isfile(str(output))
