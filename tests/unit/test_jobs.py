"""Test della coda job con motore finto."""

from __future__ import annotations

import os
import time

from app import events
from app.core.engine import FakeEngine, InferParams
from app.core.jobs import CANCELED, DONE, FAILED, JobQueue


def make_queue(manager, engine, paths) -> JobQueue:
    queue = JobQueue(engine, manager, events.BUS, jobs_state_path=paths.jobs_state_path)
    queue.start()
    return queue


def prepare(manager, tmp_path, model_file):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    manager.load()
    manager.settings.audio.input_dir = str(input_dir)
    manager.settings.audio.output_dir = str(output_dir)
    manager.settings.audio.model_path = model_file
    manager.save()
    source = input_dir / "voce.wav"
    source.write_bytes(b"RIFF")
    return str(source), str(output_dir)


def wait_state(queue, job_id, states, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = queue.get(job_id)
        if job and job.state in states:
            return job
        time.sleep(0.02)
    raise AssertionError("timeout in attesa di %s per %s" % (states, job_id))


def test_enqueue_completes(manager, paths, tmp_path, model_file):
    source, output_dir = prepare(manager, tmp_path, model_file)
    queue = make_queue(manager, FakeEngine(duration_s=0.1), paths)
    try:
        job = queue.enqueue(source, InferParams(), source="manual")
        assert job.state in ("queued", "running", "done")
        done = wait_state(queue, job.id, (DONE, FAILED, CANCELED))
        assert done.state == DONE, done.error_message
        assert os.path.isfile(done.output_path)
        assert os.path.basename(done.output_path) == "voce.wav"
        assert queue.stats()["done"] == 1
    finally:
        queue.stop()


def test_dedupe_returns_same_job(manager, paths, tmp_path, model_file):
    source, _ = prepare(manager, tmp_path, model_file)
    queue = make_queue(manager, FakeEngine(duration_s=0.05), paths)
    try:
        first = queue.enqueue(source, InferParams())
        wait_state(queue, first.id, (DONE,))
        second = queue.enqueue(source, InferParams())
        assert second.id == first.id
    finally:
        queue.stop()


def test_cancel_queued_job(manager, paths, tmp_path, model_file):
    source, _ = prepare(manager, tmp_path, model_file)
    queue = make_queue(manager, FakeEngine(duration_s=0.3, delay_s=1.0), paths)
    try:
        first = queue.enqueue(source, InferParams())
        wait_state(queue, first.id, ("running",))
        second_input = os.path.join(os.path.dirname(source), "secondo.wav")
        with open(second_input, "wb") as handle:
            handle.write(b"RIFF")
        second = queue.enqueue(second_input, InferParams())
        queue.cancel(second.id)
        canceled = wait_state(queue, second.id, (CANCELED,))
        assert canceled.error_code == "canceled"
        assert queue.stats()["canceled"] == 1
    finally:
        queue.stop()


def test_cancel_running_job(manager, paths, tmp_path, model_file):
    source, _ = prepare(manager, tmp_path, model_file)
    queue = make_queue(manager, FakeEngine(duration_s=0.1, delay_s=3.0), paths)
    try:
        job = queue.enqueue(source, InferParams())
        wait_state(queue, job.id, ("running",))
        queue.cancel(job.id)
        canceled = wait_state(queue, job.id, (CANCELED,), timeout=10.0)
        assert canceled.state == CANCELED
    finally:
        queue.stop()


def test_failure_is_recorded(manager, paths, tmp_path, model_file):
    source, _ = prepare(manager, tmp_path, model_file)
    queue = make_queue(manager, FakeEngine(fail_with="errore simulato"), paths)
    try:
        job = queue.enqueue(source, InferParams())
        failed = wait_state(queue, job.id, (FAILED,))
        assert failed.error_code == "engine_error"
        assert "simulato" in failed.error_message
    finally:
        queue.stop()


def test_persisted_queued_job_is_marked_interrupted(manager, paths, tmp_path, model_file):
    """Un job rimasto 'queued' su disco (crash) non deve mai restare appeso."""
    import json

    prepare(manager, tmp_path, model_file)
    record = {
        "id": "deadbeef",
        "input_path": str(tmp_path / "in" / "voce.wav"),
        "output_path": str(tmp_path / "out" / "voce.wav"),
        "model_path": model_file,
        "index_path": "",
        "params": {},
        "source": "manual",
        "state": "queued",
        "created_at": time.time() - 10,
    }
    with open(paths.jobs_state_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    queue = JobQueue(
        FakeEngine(), manager, events.BUS, jobs_state_path=paths.jobs_state_path
    )
    loaded = queue.get("deadbeef")
    assert loaded is not None
    assert loaded.state == FAILED
    assert loaded.error_code == "interrupted"


def test_unique_output_name(manager, paths, tmp_path, model_file):
    source, output_dir = prepare(manager, tmp_path, model_file)
    queue = make_queue(manager, FakeEngine(duration_s=0.05), paths)
    try:
        first = queue.enqueue(source, InferParams())
        wait_state(queue, first.id, (DONE,))
        second = queue.enqueue(source, InferParams(), dedupe=False)
        assert second.output_path != first.output_path
        assert os.path.basename(second.output_path) == "voce (2).wav"
    finally:
        queue.stop()
