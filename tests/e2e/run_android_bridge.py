"""E2E del ponte Android/Dropbox: telefono -> AudioIn -> PC -> AudioOut -> telefono.

Simula l'app Android scrivendo il config piatto e un WAV in AudioIn, usa il vero
watcher + JobQueue con FakeEngine (nessuna GPU) e verifica che il risultato compaia
in AudioOut con lo stesso nome.

Esecuzione:  runtime\\python.exe -B tests\\e2e\\run_android_bridge.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import events  # noqa: E402
from app.android_bridge import (  # noqa: E402
    ConfigSync,
    import_shared_config,
    prepare,
    read_models_count,
    shared_paths,
    sync_shared,
)
from app.core.engine import FakeEngine  # noqa: E402
from app.core.jobs import JobQueue  # noqa: E402
from app.core.watcher import Watcher  # noqa: E402
from app.paths import AppPaths  # noqa: E402
from app.settings import SettingsManager  # noqa: E402


def make_wav(path: str, seconds: float = 0.2, rate: int = 16000) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x01" * int(seconds * rate))


def wait_for(path: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(path) and os.path.getsize(path) > 44:
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    work = os.path.join(ROOT, "data", "_android_e2e")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    paths = AppPaths(app_root=work, data_dir=os.path.join(work, "data"), portable=True)
    paths.ensure()
    os.makedirs(paths.models_dir, exist_ok=True)
    model = os.path.join(paths.models_dir, "Nicola.pth")
    index = os.path.join(paths.models_dir, "Nicola.index")
    with open(model, "wb") as handle:
        handle.write(b"model")
    with open(index, "wb") as handle:
        handle.write(b"index")
    manager = SettingsManager(paths)
    manager.load()

    engine = FakeEngine(duration_s=0.2)
    queue = JobQueue(engine, manager, events.EventBus(), jobs_state_path=paths.jobs_state_path)
    queue.start()
    watcher = Watcher(settings_manager=manager, job_queue=queue)
    shared = os.path.join(work, "Dropbox", "TestRVC")

    summary = prepare(manager, paths, shared_dir=shared, watcher=watcher)
    print("[e2e] preset: %s" % {k: summary[k] for k in ("shared_dir", "models", "watcher_started")})
    assert summary["watcher_started"] is True
    paths_shared = shared_paths(shared, manager.settings.android)
    assert os.path.isdir(paths_shared["input_dir"])
    assert os.path.isdir(paths_shared["output_dir"])

    # 1) l'app Android scrive il config.json piatto sul "Dropbox"
    phone_config = {
        "input_dir": "/TestRVC/AudioIn",
        "output_dir": "/TestRVC/AudioOut",
        "model_path": model,
        "index_path": index,
        "pitch": 2,
        "method": "harvest",
        "protect": 0.3,
        "index_rate": 0.4,
    }
    with open(paths_shared["config_path"], "w", encoding="utf-8") as handle:
        json.dump(phone_config, handle)
    result = import_shared_config(manager)
    print("[e2e] config applicata: %s" % result["applied"])
    assert manager.settings.audio.pitch == 2
    assert manager.settings.audio.method == "harvest"

    sync_info = sync_shared(manager, paths)
    assert read_models_count(sync_info["models_path"]) >= 1
    print("[e2e] modelli.txt: %s modelli" % sync_info["models"])

    # 2) il telefono carica un WAV in AudioIn
    incoming = os.path.join(paths_shared["input_dir"], "telefono.wav")
    make_wav(incoming, seconds=0.3)
    expected = os.path.join(paths_shared["output_dir"], "telefono.wav")
    started = time.time()
    assert wait_for(expected), "il PC non ha prodotto AudioOut/telefono.wav"
    print("[e2e] conversione 1 completata in %.1fs: %s" % (time.time() - started, expected))
    with wave.open(expected, "rb") as handle:
        assert handle.getnframes() > 0

    # 3) stesso nome riconvertito (il telefono cancella e ricarica)
    time.sleep(0.2)
    os.remove(incoming)
    make_wav(incoming, seconds=0.4)
    time.sleep(0.2)
    os.remove(expected)
    started = time.time()
    assert wait_for(expected), "il PC non ha riconvertito lo stesso nome"
    print("[e2e] riconversione stesso nome in %.1fs" % (time.time() - started))

    # 4) config sync automatico (file cambiato dal telefono)
    sync = ConfigSync(manager, bus=None, interval_s=1.0)
    with open(paths_shared["config_path"], "w", encoding="utf-8") as handle:
        json.dump({"pitch": -4, "method": "pm"}, handle)
    applied = sync.apply_now()
    assert applied is not None and "pitch" in applied["applied"]
    assert manager.settings.audio.pitch == -4
    print("[e2e] config sync: %s" % applied["applied"])

    watcher.stop()
    queue.stop()
    shutil.rmtree(work, ignore_errors=True)
    print("[e2e] OK — flusso telefono -> Dropbox -> PC -> Dropbox verificato")
    return 0


if __name__ == "__main__":
    sys.exit(main())
