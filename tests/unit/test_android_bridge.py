"""Test del ponte Android/Dropbox (config locale, modelli, preset)."""

from __future__ import annotations

import json
import os

from app import android_bridge as bridge
from app.settings import SettingsManager


def _make_dropbox_info(tmp_path, monkeypatch):
    root = tmp_path / "Dropbox"
    root.mkdir()
    info_dir = tmp_path / "Local" / "Dropbox"
    info_dir.mkdir(parents=True)
    (info_dir / "info.json").write_text(
        json.dumps({"personal": {"path": str(root), "display_name": "Mario"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Home"))
    return root


def test_detect_dropbox_roots(tmp_path, monkeypatch):
    root = _make_dropbox_info(tmp_path, monkeypatch)
    roots = bridge.detect_dropbox_roots()
    assert any(os.path.normcase(item["path"]) == os.path.normcase(str(root)) for item in roots)
    item = next(item for item in roots if os.path.normcase(item["path"]) == os.path.normcase(str(root)))
    assert item["shared_dir"].endswith("TestRVC")
    assert item["has_shared"] is False
    (root / "TestRVC").mkdir()
    refreshed = bridge.detect_dropbox_roots()
    assert any(item["has_shared"] for item in refreshed)


def test_shared_paths_and_remote_dirs():
    class FakeAndroid:
        input_subdir = "AudioIn"
        output_subdir = "Out"
        config_name = "config.json"
        models_name = "modelli.txt"
        shared_dir = os.path.join("C:\\", "Dropbox", "TestRVC")

    paths = bridge.shared_paths(FakeAndroid.shared_dir, FakeAndroid)
    assert paths["input_dir"].endswith(os.path.join("TestRVC", "AudioIn"))
    assert paths["output_dir"].endswith(os.path.join("TestRVC", "Out"))
    assert paths["config_path"].endswith("config.json")
    assert paths["models_path"].endswith("modelli.txt")
    assert bridge.remote_dir_for("input", FakeAndroid) == "/TestRVC/AudioIn"
    assert bridge.remote_dir_for("output", FakeAndroid) == "/TestRVC/Out"


def test_hybrid_config_has_flat_android_keys(manager: SettingsManager):
    manager.settings.audio.model_path = "C:\\models\\voce.pth"
    manager.settings.audio.index_path = "C:\\models\\voce.index"
    manager.settings.audio.pitch = 3
    manager.settings.audio.method = "harvest"
    manager.settings.android.shared_dir = "C:\\Dropbox\\TestRVC"
    data = bridge.hybrid_config(manager.settings)
    assert data["audio"]["pitch"] == 3
    assert data["pitch"] == 3
    assert data["method"] == "harvest"
    assert data["model_path"] == "C:\\models\\voce.pth"
    assert data["index_path"].endswith("voce.index")
    assert data["input_dir"] == "/TestRVC/AudioIn"
    assert data["android_bridge"]["app"] == "rvc-portable-android"


def test_write_models_file(tmp_path):
    target = tmp_path / "modelli.txt"
    entries = [
        {"name": "Nicola", "path": "C:\\m\\nicola.pth", "index_path": "C:\\m\\nicola.index"},
        {"name": "Nicola", "path": "C:\\m\\nicola2.pth", "index_path": ""},
        {"name": "SenzaPath"},
    ]
    result = bridge.write_models_file(str(target), entries)
    assert result["count"] == 2
    text = target.read_text(encoding="utf-8")
    assert "# modelli.txt" in text
    assert "Nicola | C:\\m\\nicola.pth | C:\\m\\nicola.index" in text
    assert "Nicola (2) | C:\\m\\nicola2.pth |" in text
    assert bridge.read_models_count(str(target)) == 2


def test_apply_payload_android_flat(manager: SettingsManager, tmp_path):
    shared = tmp_path / "Dropbox" / "TestRVC"
    (shared / "AudioIn").mkdir(parents=True)
    model = tmp_path / "voce.pth"
    model.write_bytes(b"model")
    index = tmp_path / "voce.index"
    index.write_bytes(b"index")
    manager.settings.android.shared_dir = str(shared)
    payload = {
        "input_dir": "/TestRVC/AudioIn",
        "output_dir": "C:\\percorso\\inesistente",
        "model_path": str(model),
        "index_path": str(index),
        "pitch": 5,
        "method": "harvest",
        "protect": 0.4,
        "index_rate": 0.6,
    }
    result = bridge.apply_payload(manager, payload)
    audio = manager.settings.audio
    assert result["mode"] == "android"
    assert audio.pitch == 5
    assert audio.method == "harvest"
    assert abs(audio.protect - 0.4) < 1e-6
    assert abs(audio.index_rate - 0.6) < 1e-6
    assert audio.model_path == str(model)
    assert audio.index_path == str(index)
    assert os.path.isdir(audio.input_dir) and audio.input_dir.endswith("AudioIn")
    assert "output_dir" in result["skipped"]


def test_apply_payload_rejects_missing_model(manager: SettingsManager):
    result = bridge.apply_payload(
        manager,
        {"model_path": "C:\\non\\esiste.pth", "method": "fcpe", "pitch": 99},
    )
    assert "model_path" in result["skipped"]
    assert "method" in result["skipped"]
    assert manager.settings.audio.pitch == 24  # clampato nel range valido


def test_apply_payload_full_config(manager: SettingsManager):
    payload = manager.settings.public_dict()
    payload["audio"]["pitch"] = 7
    result = bridge.apply_payload(manager, payload)
    assert result["mode"] == "full"
    assert manager.settings.audio.pitch == 7


def test_prepare_creates_shared_structure(manager: SettingsManager, paths):
    os.makedirs(paths.models_dir, exist_ok=True)
    model = os.path.join(paths.models_dir, "Nicola.pth")
    with open(model, "wb") as handle:
        handle.write(b"model")
    shared = os.path.join(str(paths.data_dir), "Dropbox", "TestRVC")
    summary = bridge.prepare(manager, paths, shared_dir=shared)
    assert os.path.isdir(os.path.join(shared, "AudioIn"))
    assert os.path.isdir(os.path.join(shared, "AudioOut"))
    assert os.path.isfile(os.path.join(shared, "config.json"))
    assert os.path.isfile(os.path.join(shared, "modelli.txt"))
    settings = manager.settings
    assert settings.android.enabled is True
    assert settings.android.shared_dir == shared
    assert settings.audio.input_dir == os.path.join(shared, "AudioIn")
    assert settings.audio.output_dir == os.path.join(shared, "AudioOut")
    assert settings.audio.output_format == "wav"
    assert settings.cloud.hot_reload is True
    assert settings.cloud.local_path == os.path.join(shared, "config.json")
    assert settings.audio.model_path == model
    assert summary["models"] == 1


def test_config_sync_applies_flat_config(manager: SettingsManager, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    config_path = shared / "config.json"
    config_path.write_text(
        json.dumps({"pitch": 9, "method": "crepe", "protect": 0.1}),
        encoding="utf-8",
    )
    manager.settings.cloud.local_path = str(config_path)
    manager.settings.cloud.hot_reload = True
    manager.settings.android.enabled = True
    manager.settings.android.shared_dir = str(shared)
    sync = bridge.ConfigSync(manager, bus=None, interval_s=1.0)
    result = sync._check()
    assert result is not None
    assert manager.settings.audio.pitch == 9
    assert manager.settings.audio.method == "crepe"
    assert abs(manager.settings.audio.protect - 0.1) < 1e-6
    # i valori sono già allineati: nessuna riscrittura (meno conflitti Dropbox)
    unchanged = json.loads(config_path.read_text(encoding="utf-8"))
    assert "audio" not in unchanged
    # il PC, quando salva, esporta la forma ibrida per il telefono
    exported = bridge.export_shared_config(manager)
    assert exported["written"] is True
    rewritten = json.loads(config_path.read_text(encoding="utf-8"))
    assert "audio" in rewritten and rewritten["pitch"] == 9
    applied = sync._check()  # la forma ibrida è un config v3 completo
    assert applied is not None and applied["mode"] == "full"
    assert sync._check() is None  # nessuna modifica: non riapplica
    status = sync.status()
    assert status["applied_count"] == 2


def test_cleanup_stale_temps(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    stale = shared / "config.json.tmp-123-456"
    stale.write_text("{}", encoding="utf-8")
    old = 1_600_000_000
    os.utime(str(stale), (old, old))
    fresh = shared / "config.json.tmp-789"
    fresh.write_text("{}", encoding="utf-8")
    removed = bridge.cleanup_stale_temps(str(shared), keep_seconds=60)
    assert removed == [str(stale)]
    assert fresh.is_file()

def test_status_publisher_writes_heartbeat(manager: SettingsManager, tmp_path):
    shared = tmp_path / "shared"
    manager.settings.android.enabled = True
    manager.settings.android.shared_dir = str(shared)
    publisher = bridge.StatusPublisher(
        manager,
        {
            "engine": lambda: {"available": True, "device": "cuda"},
            "queue": lambda: {"queued": 1, "running": 0, "done": 2},
        },
    )
    data = publisher.publish_once()
    assert data is not None
    path = shared / "status.json"
    assert path.is_file()
    payload = bridge.read_status(manager)
    assert payload is not None
    assert payload["providers"]["engine"]["available"] is True
    assert payload["providers"]["queue"]["done"] == 2
    assert payload["schema"] == bridge.STATUS_SCHEMA
    assert payload["audio"]["pitch"] == manager.settings.audio.pitch


def test_export_shared_config_skips_unchanged(manager: SettingsManager, tmp_path):
    shared = tmp_path / "shared"
    manager.settings.android.enabled = True
    manager.settings.android.shared_dir = str(shared)
    manager.settings.audio.pitch = 4
    first = bridge.export_shared_config(manager)
    assert first["written"] is True
    config_path = shared / "config.json"
    first_bytes = config_path.read_bytes()
    second = bridge.export_shared_config(manager)
    assert second["written"] is False
    assert second["reason"] == "unchanged"
    assert config_path.read_bytes() == first_bytes


def test_write_models_file_skips_unchanged(tmp_path):
    target = tmp_path / "modelli.txt"
    entries = [{"name": "Voce", "path": "C:\\m\\voce.pth", "index_path": ""}]
    first = bridge.write_models_file(str(target), entries)
    assert first["written"] is True
    second = bridge.write_models_file(str(target), entries)
    assert second["written"] is False
    assert bridge.read_models_count(str(target)) == 1


def test_status_publisher_skips_unchanged_until_heartbeat(manager: SettingsManager, tmp_path):
    shared = tmp_path / "shared"
    manager.settings.android.enabled = True
    manager.settings.android.shared_dir = str(shared)
    publisher = bridge.StatusPublisher(
        manager,
        {"engine": lambda: {"available": True}},
        interval_s=5.0,
        heartbeat_s=60.0,
    )
    assert publisher.publish_once(force=False) is not None
    assert publisher.publish_once(force=False) is None
    assert publisher.status()["writes"] == 1
    assert publisher.publish_once(force=True) is not None
    assert publisher.status()["writes"] == 2
