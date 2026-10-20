"""Fixture comuni ai test unitari."""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.paths import AppPaths  # noqa: E402
from app.settings import SettingsManager  # noqa: E402


@pytest.fixture()
def paths(tmp_path) -> AppPaths:
    data = tmp_path / "data"
    app_paths = AppPaths(
        app_root=str(tmp_path),
        data_dir=str(data),
        portable=True,
    )
    app_paths.ensure()
    return app_paths


@pytest.fixture()
def manager(paths) -> SettingsManager:
    return SettingsManager(paths)


@pytest.fixture()
def model_file(tmp_path):
    path = tmp_path / "voice.pth"
    path.write_bytes(b"dummy-model")
    return str(path)
