"""Test della configurazione: migrazione, atomicita', patch, validazione."""

from __future__ import annotations

import json
import os

import pytest
from pydantic import ValidationError

from app.settings import SCHEMA_VERSION, AudioSettings, Settings


def test_defaults(manager):
    settings = manager.load()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.audio.method == "rmvpe"
    assert settings.ui.language == "it"
    assert settings.engine.device == "auto"
    assert settings.monitor.ignore_globs


def test_migrate_flat_v2(paths, manager):
    legacy = {
        "input_dir": "K:/audio/in",
        "output_dir": "K:/audio/out",
        "model_path": "K:/models/voce.pth",
        "index_path": "K:/models/voce.index",
        "pitch": 4,
        "method": "fcpe",
        "protect": 0.4,
        "index_rate": 0.5,
        "device": "dml:0",
        "language": "en",
        "cloud_config_path": "J:/Dropbox/config.json",
        "auto_reload_cloud": True,
        "dropbox_app_key": "abc123",
    }
    with open(paths.legacy_config_path, "w", encoding="utf-8") as handle:
        json.dump(legacy, handle)
    settings = manager.load()
    assert settings.audio.pitch == 4
    assert settings.audio.method == "rmvpe"  # fcpe non supportato
    assert settings.engine.device == "auto"  # dml non supportato
    assert settings.ui.language == "en"
    assert settings.cloud.dropbox.app_key == "abc123"
    assert settings.cloud.hot_reload is True
    assert settings.cloud.local_path.endswith("config.json")
    assert any("fcpe" in warning for warning in manager.warnings)
    assert os.path.isfile(paths.config_path)
    with open(paths.config_path, "r", encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["schema_version"] == SCHEMA_VERSION
    assert saved["audio"]["pitch"] == 4


def test_save_is_atomic_and_keeps_backup(manager):
    manager.settings.audio.pitch = 7
    manager.save()
    first = open(manager.paths.config_path, "rb").read()
    manager.settings.audio.pitch = 8
    manager.save()
    second = open(manager.paths.config_path, "rb").read()
    assert first != second
    assert os.path.isfile(manager.paths.backup_config_path)
    assert json.loads(first.decode("utf-8"))["audio"]["pitch"] == 7
    assert json.loads(second.decode("utf-8"))["audio"]["pitch"] == 8
    assert not [name for name in os.listdir(manager.paths.data_dir) if ".tmp-" in name]


def test_patch_nested(manager):
    manager.load()
    updated = manager.apply_patch(
        {"audio": {"pitch": -3, "method": "harvest"}, "ui": {"theme": "light"}}
    )
    assert updated.audio.pitch == -3
    assert updated.audio.method == "harvest"
    assert updated.ui.theme == "light"
    # le altre chiavi restano intatte
    assert updated.engine.device == "auto"


def test_patch_invalid_value_rejected(manager):
    manager.load()
    with pytest.raises(ValidationError):
        manager.apply_patch({"audio": {"method": "fcpe"}})


def test_device_and_method_validation():
    with pytest.raises(ValidationError):
        AudioSettings(method="fcpe")
    with pytest.raises(ValidationError):
        Settings(engine={"device": "dml:0"})
    assert Settings(engine={"device": "cuda"}).engine.device == "cuda:0"
    assert Settings(engine={"device": "cpu:"}).engine.device == "cpu"


def test_import_export(manager, tmp_path):
    manager.load()
    manager.settings.audio.pitch = 2
    exported = manager.export_dict()
    assert "exported_at" in exported
    path = tmp_path / "import.json"
    path.write_text(json.dumps(exported), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    manager.import_dict(data)
    assert manager.settings.audio.pitch == 2


def test_corrupted_config_keeps_defaults(paths, manager):
    os.makedirs(os.path.dirname(paths.config_path), exist_ok=True)
    with open(paths.config_path, "w", encoding="utf-8") as handle:
        handle.write("{non-json")
    settings = manager.load()
    assert settings.audio.method == "rmvpe"
    assert manager.warnings
