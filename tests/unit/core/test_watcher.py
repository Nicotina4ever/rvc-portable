"""Test di ``app.core.watcher``: rilevamento file stabilì, ignore globs, dedupe."""

from __future__ import annotations

import math
import os
import time
import wave


def _write_wav(path, seconds: float = 0.1, sample_rate: int = 8000):
    frames = int(seconds * sample_rate)
    payload = bytearray()
    for index in range(frames):
        value = int(8000 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
        payload += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return str(path)


def _make_watcher(manager, paths, received, states=None):
    from app.core.watcher import Watcher

    watcher = Watcher(
        on_file=received.append,
        on_state=(states.append if states is not None else None),
        settings_manager=manager,
        processed_path=paths.processed_state_path,
    )
    return watcher


def _configure(manager, input_dir, output_dir, stability_ms: int = 100, mode: str = "native"):
    manager.settings.audio.input_dir = str(input_dir)
    manager.settings.audio.output_dir = str(output_dir)
    manager.settings.monitor.watch_mode = mode
    manager.settings.monitor.stability_ms = stability_ms
    manager.settings.monitor.poll_interval_s = 0.5
    manager.settings.monitor.ignore_output_dir = True


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_start_stop_status(tmp_path, manager, paths):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    _configure(manager, input_dir, output_dir)
    watcher = _make_watcher(manager, paths, [])
    try:
        status = watcher.start(str(input_dir))
        assert status["running"] is True
        assert status["dir"] == str(input_dir)
        assert status["mode"] in ("native", "polling")
        assert status["processed_session"] == 0
        stopped = watcher.stop()
        assert stopped["running"] is False
    finally:
        watcher.stop()


def test_detects_stable_file(tmp_path, manager, paths):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    _configure(manager, input_dir, output_dir, stability_ms=100)
    received = []
    states = []
    watcher = _make_watcher(manager, paths, received, states)
    try:
        watcher.start(str(input_dir))
        _write_wav(input_dir / "voce.wav")
        assert _wait_for(lambda: len(received) == 1, timeout=5.0), received
        assert received[0].endswith("voce.wav")
        assert watcher.status()["processed_session"] == 1
        assert states
    finally:
        watcher.stop()


def test_ignores_globs_and_output_dir(tmp_path, manager, paths):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    _configure(manager, input_dir, output_dir, stability_ms=50)
    received = []
    watcher = _make_watcher(manager, paths, received)
    try:
        watcher.start(str(input_dir))
        (input_dir / "lavoro.tmp").write_bytes(b"tmp")
        _write_wav(output_dir / "convertito.wav")
        (input_dir / "nota.txt").write_text("non audio", encoding="utf-8")
        time.sleep(1.0)
        assert received == []
        _write_wav(input_dir / "voce.wav")
        assert _wait_for(lambda: len(received) == 1, timeout=5.0), received
    finally:
        watcher.stop()


def test_process_existing_and_persistent_dedupe(tmp_path, manager, paths):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    _configure(manager, input_dir, output_dir)
    _write_wav(input_dir / "uno.wav")
    _write_wav(input_dir / "due.wav")
    received = []
    watcher = _make_watcher(manager, paths, received)
    first = watcher.process_existing(str(input_dir))
    assert first == {"enqueued": 2, "skipped": 0}
    assert len(received) == 2
    assert os.path.isfile(paths.processed_state_path)

    # Un nuovo watcher (riavvio dell'app) ricorda i file gia' processati.
    received_again = []
    watcher2 = _make_watcher(manager, paths, received_again)
    second = watcher2.process_existing(str(input_dir))
    assert second["enqueued"] == 0
    assert second["skipped"] == 2
    assert received_again == []

    # Un file modificato (mtime/size diversi) viene invece riprocessato.
    _write_wav(input_dir / "due.wav", seconds=0.2)
    third = watcher2.process_existing(str(input_dir))
    assert third["enqueued"] == 1
    assert received_again == [str(input_dir / "due.wav")]


def test_start_with_process_existing(tmp_path, manager, paths):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    _configure(manager, input_dir, output_dir, stability_ms=50)
    _write_wav(input_dir / "pronto.wav")
    received = []
    watcher = _make_watcher(manager, paths, received)
    try:
        status = watcher.start(str(input_dir), process_existing=True)
        assert status["processed_session"] == 1
        assert len(received) == 1
    finally:
        watcher.stop()


def test_invalid_directory_raises(manager, paths, tmp_path):
    import pytest

    watcher = _make_watcher(manager, paths, [])
    with pytest.raises(ValueError):
        watcher.start(str(tmp_path / "non-esiste"))
    with pytest.raises(ValueError):
        watcher.process_existing(str(tmp_path / "non-esiste"))


def test_on_state_receives_status(tmp_path, manager, paths):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    _configure(manager, input_dir, output_dir, stability_ms=50)
    received = []
    states = []
    watcher = _make_watcher(manager, paths, received, states)
    try:
        watcher.start(str(input_dir))
        _write_wav(input_dir / "voce.wav")
        assert _wait_for(lambda: len(states) >= 1, timeout=5.0), states
        assert "running" in states[-1]
        assert "processed_session" in states[-1]
    finally:
        watcher.stop()
