"""Fixture per i test di integrazione delle API HTTP.

Costruisce un'app FastAPI completa (router reali, middleware di sicurezza) con
percorsi/coda/watcher temporanei e un motore finto: nessun accesso a torch,
nessuna rete reale.
"""

from __future__ import annotations

import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import events  # noqa: E402
from app.api.app_factory import create_app  # noqa: E402
from app.core.engine import FakeEngine  # noqa: E402
from app.core.jobs import JobQueue  # noqa: E402
from app.core.watcher import Watcher  # noqa: E402
from app.paths import AppPaths  # noqa: E402
from app.settings import SettingsManager  # noqa: E402

PORT = 8877
TOKEN = "integration-token"
BASE_URL = "http://127.0.0.1:%d" % PORT
AUTH = {"Authorization": "Bearer %s" % TOKEN}


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Blocca ogni HTTP reale: i test devono usare session factory finte."""
    import requests

    def blocked(*args, **kwargs):
        raise AssertionError(
            "test di integrazione: richiesta HTTP reale non consentita (%r)" % (args,)
        )

    monkeypatch.setattr(requests.Session, "request", blocked)


@pytest.fixture()
def paths(tmp_path) -> AppPaths:
    app_paths = AppPaths(
        app_root=str(tmp_path), data_dir=str(tmp_path / "data"), portable=True
    )
    app_paths.ensure()
    os.makedirs(app_paths.models_dir, exist_ok=True)
    return app_paths


@pytest.fixture()
def manager(paths) -> SettingsManager:
    settings_manager = SettingsManager(paths)
    settings_manager.load()
    return settings_manager


@pytest.fixture()
def engine() -> FakeEngine:
    return FakeEngine(duration_s=0.1)


@pytest.fixture()
def job_queue(engine, manager, paths):
    queue = JobQueue(
        engine,
        manager,
        events.EventBus(),
        jobs_state_path=paths.jobs_state_path,
    )
    queue.start()
    try:
        yield queue
    finally:
        queue.stop()


@pytest.fixture()
def watcher(manager, job_queue) -> Watcher:
    return Watcher(settings_manager=manager, job_queue=job_queue)


@pytest.fixture()
def app(paths, manager, engine, job_queue, watcher):
    return create_app(
        paths=paths,
        settings_manager=manager,
        engine=engine,
        job_queue=job_queue,
        watcher=watcher,
        bus=events.EventBus(),
        token=TOKEN,
        port=PORT,
        started_at=time.time(),
    )


@pytest.fixture()
def client(app):
    with TestClient(app, base_url=BASE_URL) as test_client:
        yield test_client


@pytest.fixture()
def auth() -> dict:
    return dict(AUTH)
