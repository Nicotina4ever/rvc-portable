"""Test della coda job in modalita' Android (output con lo stesso nome input)."""

from __future__ import annotations

import os
import time
import wave

from app import events
from app.core.engine import FakeEngine, InferParams
from app.core.jobs import DONE, JobQueue


def make_wav(path: str, seconds: float = 0.1, rate: int = 16000) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x01" * int(seconds * rate))


def wait_done(queue: JobQueue, job_id: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = queue.get(job_id)
        if job is not None and job.state in (DONE, "failed", "canceled"):
            return job
        time.sleep(0.05)
    raise AssertionError("job non completato: %s" % job_id)


def _setup(manager, tmp_path, model_file):
    input_dir = tmp_path / "AudioIn"
    output_dir = tmp_path / "AudioOut"
    input_dir.mkdir()
    output_dir.mkdir()
    manager.settings.audio.input_dir = str(input_dir)
    manager.settings.audio.output_dir = str(output_dir)
    manager.settings.audio.model_path = model_file
    manager.settings.audio.output_format = "wav"
    manager.settings.android.enabled = True
    manager.settings.android.same_name_output = True
    return input_dir, output_dir


def test_monitor_output_keeps_input_name(manager, paths, tmp_path, model_file):
    input_dir, output_dir = _setup(manager, tmp_path, model_file)
    queue = JobQueue(FakeEngine(), manager, events.EventBus())
    queue.start()
    try:
        source = input_dir / "prova.wav"
        make_wav(str(source))
        job = queue.enqueue(
            str(source),
            InferParams.from_audio(manager.settings.audio),
            source="monitor",
        )
        assert os.path.basename(job.output_path) == "prova.wav"
        done = wait_done(queue, job.id)
        assert done.state == DONE
        assert os.path.isfile(os.path.join(str(output_dir), "prova.wav"))

        # stesso nome, contenuto nuovo: deve riconvertire e sovrascrivere
        time.sleep(0.01)
        make_wav(str(source), seconds=0.2)
        second = queue.enqueue(
            str(source),
            InferParams.from_audio(manager.settings.audio),
            source="monitor",
        )
        assert second.id != job.id
        assert os.path.basename(second.output_path) == "prova.wav"
        wait_done(queue, second.id)
    finally:
        queue.stop()


def test_manual_output_uses_unique_name(manager, tmp_path, model_file):
    input_dir, output_dir = _setup(manager, tmp_path, model_file)
    (output_dir / "prova.wav").write_bytes(b"old")
    queue = JobQueue(FakeEngine(), manager, events.EventBus())
    queue.start()
    try:
        source = input_dir / "prova.wav"
        make_wav(str(source))
        job = queue.enqueue(
            str(source),
            InferParams.from_audio(manager.settings.audio),
            source="manual",
        )
        assert os.path.basename(job.output_path) == "prova (2).wav"
        wait_done(queue, job.id)
    finally:
        queue.stop()


def test_explicit_output_path(manager, tmp_path, model_file):
    input_dir, _output_dir = _setup(manager, tmp_path, model_file)
    queue = JobQueue(FakeEngine(), manager, events.EventBus())
    queue.start()
    try:
        source = input_dir / "voce.wav"
        make_wav(str(source))
        explicit = tmp_path / "custom" / "out.wav"
        job = queue.enqueue(
            str(source),
            InferParams.from_audio(manager.settings.audio),
            source="monitor",
            output_path=str(explicit),
        )
        assert job.output_path == str(explicit)
        wait_done(queue, job.id)
        assert explicit.is_file()
    finally:
        queue.stop()
