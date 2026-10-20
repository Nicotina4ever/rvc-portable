"""Smoke test senza pytest: verifica il cablaggio app/API/job sul runtime 3.9.

Esegui:  runtime\\python.exe -B tests\\smoke_core.py
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from app import events  # noqa: E402
from app.api.app_factory import create_app  # noqa: E402
from app.core.engine import FakeEngine  # noqa: E402
from app.core.jobs import JobQueue  # noqa: E402
from app.core.watcher import Watcher  # noqa: E402
from app.paths import AppPaths  # noqa: E402
from app.settings import SettingsManager  # noqa: E402

TOKEN = "smoke-token"
PORT = 8765


def make_wav(path: str, seconds: float = 0.25, rate: int = 16000) -> None:
    frames = int(seconds * rate)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x01" * frames)


def main() -> int:
    data_dir = os.path.join(ROOT, "data", "_smoke")
    if os.path.isdir(data_dir):
        shutil.rmtree(data_dir)
    paths = AppPaths.create(data_dir=data_dir, prefer_portable=True)
    manager = SettingsManager(paths)
    manager.load()

    input_dir = os.path.join(data_dir, "in")
    output_dir = os.path.join(data_dir, "out")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(data_dir, "dummy.pth")
    with open(model_path, "w", encoding="utf-8") as handle:
        handle.write("dummy")
    manager.settings.audio.input_dir = input_dir
    manager.settings.audio.output_dir = output_dir
    manager.settings.audio.model_path = model_path
    manager.save(manager.settings)

    engine = FakeEngine(duration_s=0.25)
    queue = JobQueue(
        engine, manager, events.BUS, jobs_state_path=paths.jobs_state_path
    )
    queue.start()
    watcher = Watcher(settings_manager=manager, job_queue=queue)
    app = create_app(
        paths=paths,
        settings_manager=manager,
        engine=engine,
        job_queue=queue,
        watcher=watcher,
        bus=events.BUS,
        token=TOKEN,
        port=PORT,
    )
    client = TestClient(app, base_url="http://127.0.0.1:%d" % PORT)
    auth = {"Authorization": "Bearer %s" % TOKEN}

    assert client.get("/api/health").status_code == 200, "health senza token"
    assert client.get("/api/settings").status_code == 401, "settings deve richiedere token"
    assert client.get("/api/settings", headers=auth).status_code == 200
    assert client.post("/api/settings", json={}, headers={"Origin": "http://evil.test"}).status_code == 403

    input_path = os.path.join(input_dir, "voce.wav")
    make_wav(input_path)
    response = client.post("/api/jobs", json={"input": input_path}, headers=auth)
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["state"] in ("queued", "running", "done"), job

    result = None
    for _ in range(200):
        got = client.get("/api/jobs/%s" % job["id"], headers=auth)
        assert got.status_code == 200, got.text
        result = got.json()
        if result["state"] in ("done", "failed", "canceled"):
            break
        time.sleep(0.02)
    assert result and result["state"] == "done", result
    assert os.path.isfile(result["output_path"]), result["output_path"]

    audio = client.get("/api/jobs/%s/audio/output" % job["id"], headers=auth)
    assert audio.status_code == 200, audio.text
    ranged = client.get(
        "/api/jobs/%s/audio/output" % job["id"],
        headers=dict(auth, Range="bytes=0-15"),
    )
    assert ranged.status_code == 206, ranged.status_code
    assert len(ranged.content) == 16
    assert ranged.headers.get("accept-ranges") == "bytes"

    listed = client.get("/api/jobs", headers=auth).json()
    assert listed["stats"]["done"] >= 1, listed["stats"]

    queue.stop()
    shutil.rmtree(data_dir, ignore_errors=True)
    print("SMOKE OK: health, auth, settings, jobs, audio range, stats")
    return 0


if __name__ == "__main__":
    sys.exit(main())
