"""Smoke test live: avvia uvicorn in un thread e verifica SSE + job + shutdown.

Esegui: runtime\\python.exe -B tests\\smoke_live.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import wave

import requests
import uvicorn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import events  # noqa: E402
from app.api.app_factory import create_app  # noqa: E402
from app.core.engine import FakeEngine  # noqa: E402
from app.core.jobs import JobQueue  # noqa: E402
from app.core.watcher import Watcher  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402
from app.paths import AppPaths  # noqa: E402
from app.security import find_free_port  # noqa: E402
from app.settings import SettingsManager  # noqa: E402


def make_wav(path: str, seconds: float = 0.2, rate: int = 16000) -> None:
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x01" * int(seconds * rate))


def main() -> int:
    data_dir = os.path.join(ROOT, "data", "_smoke_live")
    if os.path.isdir(data_dir):
        shutil.rmtree(data_dir)
    paths = AppPaths.create(data_dir=data_dir, prefer_portable=True)
    setup_logging(paths, console=False)
    manager = SettingsManager(paths)
    manager.load()
    input_dir = os.path.join(data_dir, "in")
    output_dir = os.path.join(data_dir, "out")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    model = os.path.join(data_dir, "dummy.pth")
    with open(model, "w", encoding="utf-8") as handle:
        handle.write("dummy")
    manager.settings.audio.input_dir = input_dir
    manager.settings.audio.output_dir = output_dir
    manager.settings.audio.model_path = model
    manager.save()

    engine = FakeEngine(duration_s=0.2)
    queue = JobQueue(engine, manager, events.BUS, jobs_state_path=paths.jobs_state_path)
    queue.start()
    watcher = Watcher(settings_manager=manager, job_queue=queue)
    token = "live-token"
    port = find_free_port()
    app = create_app(
        paths=paths,
        settings_manager=manager,
        engine=engine,
        job_queue=queue,
        watcher=watcher,
        bus=events.BUS,
        token=token,
        port=port,
    )
    shutdown = threading.Event()
    app.state.shutdown_callback = shutdown.set
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % port
    auth = {"Authorization": "Bearer %s" % token}
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if requests.get(base + "/api/health", timeout=1).status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(0.1)
    else:
        print("FAIL: server non avviato")
        return 1

    input_path = os.path.join(input_dir, "voce.wav")
    make_wav(input_path)

    sse_url = base + "/api/events?t=%s" % token
    received = []

    def enqueue() -> None:
        time.sleep(1.0)
        try:
            response = requests.post(
                base + "/api/jobs", json={"input": input_path}, headers=auth, timeout=10
            )
            print("POST /api/jobs -> %s" % response.status_code)
            assert response.status_code == 200, response.text
        except Exception as exc:  # noqa: BLE001
            print("POST /api/jobs FALLITA: %r" % (exc,))

    threading.Thread(target=enqueue, daemon=True).start()
    try:
        response = requests.get(sse_url, stream=True, timeout=(3, 12))
        assert response.status_code == 200, response.status_code
        event_type = None
        for raw in response.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            line = raw.strip()
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                received.append((event_type, payload))
                types = {item[0] for item in received}
                print("SSE %-8s %s" % (event_type, str(payload)[:100]))
                if "job" in types and "hello" in types and "log" in types:
                    break
            if time.time() > deadline:
                break
        response.close()
    except requests.RequestException as exc:
        print("FAIL SSE: %s" % exc)
        return 1

    types = {item[0] for item in received}
    print("eventi ricevuti: %s (%d)" % (sorted(types), len(received)))
    assert "hello" in types, received
    assert "job" in types, types
    assert "log" in types, types

    shutdown_response = requests.post(
        base + "/api/system/shutdown", headers=auth, timeout=10
    )
    assert shutdown_response.status_code == 200, shutdown_response.text
    assert shutdown.wait(3.0), "callback di shutdown non chiamata"

    server.should_exit = True
    queue.stop()
    time.sleep(0.3)
    shutil.rmtree(data_dir, ignore_errors=True)
    print("SMOKE LIVE OK: health, SSE (hello/job/log), shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
