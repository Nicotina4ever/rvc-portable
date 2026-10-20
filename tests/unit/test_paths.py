"""Test della risoluzione percorsi e dell'override configurazione."""

from __future__ import annotations

import os

from app.paths import AppPaths, user_data_dir


def test_portable_data_dir(tmp_path):
    data = tmp_path / "data"
    paths = AppPaths.create(app_root=str(tmp_path), data_dir=str(data))
    assert paths.portable is True
    assert paths.data_dir == str(data)
    assert os.path.isdir(paths.logs_dir)
    assert paths.config_path == os.path.join(str(data), "config.json")
    assert paths.models_dir.endswith("Modelli")


def test_config_override_changes_data_dir(tmp_path):
    config = tmp_path / "cloud" / "rvc.json"
    config.parent.mkdir()
    paths = AppPaths.create(app_root=str(tmp_path), config_path=str(config))
    assert paths.config_path == str(config)
    assert paths.data_dir == str(config.parent)
    assert paths.portable is True


def test_user_data_dir_not_empty():
    assert user_data_dir()
    assert os.path.isabs(user_data_dir())


def test_describe_has_expected_keys(tmp_path):
    paths = AppPaths.create(app_root=str(tmp_path), data_dir=str(tmp_path / "d"))
    described = paths.describe()
    for key in ("app_root", "data_dir", "config_path", "logs_dir", "models_dir", "platform"):
        assert key in described
