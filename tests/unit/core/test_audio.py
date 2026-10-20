"""Test di ``app.core.audio``: waveform normalizzata, cache e probe metadati."""

from __future__ import annotations

import math
import os
import wave

import pytest

from app.core.audio import clear_cache, probe_audio, waveform_peaks


def _write_wav(path, seconds: float = 0.5, sample_rate: int = 44100, amplitude: int = 16000):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = int(seconds * sample_rate)
    payload = bytearray()
    for index in range(frames):
        value = int(amplitude * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
        payload += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return str(path)


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    directory = tmp_path / "waveform-cache"
    monkeypatch.setenv("RVC_WAVEFORM_CACHE", str(directory))
    return directory


def test_waveform_peaks_shape_and_range(tmp_path, cache_dir):
    audio = _write_wav(tmp_path / "voce.wav")
    result = waveform_peaks(audio, buckets=128)
    peaks = result["peaks"]
    assert len(peaks) == 128
    assert all(0.0 <= float(value) <= 1.0 for value in peaks)
    assert max(peaks) == pytest.approx(1.0, abs=1e-3)
    assert result["sample_rate"] == 44100
    assert result["duration_s"] == pytest.approx(0.5, abs=0.05)


def test_waveform_default_buckets(tmp_path, cache_dir):
    audio = _write_wav(tmp_path / "voce.wav")
    assert len(waveform_peaks(audio)["peaks"]) == 800


def test_waveform_silence_gives_zero_peaks(tmp_path, cache_dir):
    audio = _write_wav(tmp_path / "silenzio.wav", seconds=0.2, amplitude=0)
    peaks = waveform_peaks(audio, buckets=32)["peaks"]
    assert peaks == [0.0] * 32


def test_waveform_cache_is_written_and_reused(tmp_path, cache_dir):
    audio = _write_wav(tmp_path / "voce.wav")
    first = waveform_peaks(audio, buckets=64)
    cached_files = list(cache_dir.glob("*.json"))
    assert len(cached_files) == 1
    mtime = cached_files[0].stat().st_mtime_ns
    second = waveform_peaks(audio, buckets=64)
    assert second == first
    assert cached_files[0].stat().st_mtime_ns == mtime
    # Il cambio di mtime invalida la cache.
    stat = os.stat(audio)
    os.utime(audio, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    waveform_peaks(audio, buckets=64)
    assert len(list(cache_dir.glob("*.json"))) == 2


def test_clear_cache(tmp_path, cache_dir):
    audio = _write_wav(tmp_path / "voce.wav")
    waveform_peaks(audio, buckets=16)
    assert clear_cache() == 1


def test_probe_audio(tmp_path, cache_dir):
    audio = _write_wav(tmp_path / "voce.wav", seconds=0.25, sample_rate=22050)
    info = probe_audio(audio)
    assert info["sample_rate"] == 22050
    assert info["channels"] == 1
    assert info["duration_s"] == pytest.approx(0.25, abs=0.02)
    assert info["format"]


def test_missing_file_raises(tmp_path, cache_dir):
    with pytest.raises(FileNotFoundError):
        waveform_peaks(str(tmp_path / "non-esiste.wav"))
    with pytest.raises(FileNotFoundError):
        probe_audio(str(tmp_path / "non-esiste.wav"))


@pytest.mark.parametrize("buckets", [0, -3, "abc"])
def test_invalid_buckets(tmp_path, cache_dir, buckets):
    audio = _write_wav(tmp_path / "voce.wav")
    with pytest.raises(ValueError):
        waveform_peaks(audio, buckets=buckets)


def test_unknown_format_raises_value_error(tmp_path, cache_dir):
    broken = tmp_path / "rotto.wav"
    broken.write_bytes(b"non e' un wav")
    with pytest.raises(ValueError):
        waveform_peaks(str(broken))


def test_flac_supported_when_soundfile_available(tmp_path, cache_dir):
    sf = pytest.importorskip("soundfile")
    import numpy as np

    path = tmp_path / "voce.flac"
    samples = np.sin(np.linspace(0, 40, 16000)).astype("float32") * 0.5
    sf.write(str(path), samples, 16000, format="FLAC")
    info = probe_audio(str(path))
    assert info["sample_rate"] == 16000
    peaks = waveform_peaks(str(path), buckets=40)["peaks"]
    assert len(peaks) == 40
    assert max(peaks) == pytest.approx(1.0, abs=1e-3)
