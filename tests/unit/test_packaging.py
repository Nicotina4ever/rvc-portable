"""Test del packaging GitHub: installer, asset runtime e igiene repository."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import build_runtime_asset as asset  # noqa: E402
from tools import check_repo  # noqa: E402


def test_install_conf_has_required_keys():
    conf = asset.parse_install_conf()
    for key in (
        "RUNTIME_WINDOWS_URL",
        "RUNTIME_WINDOWS_SHA256",
        "RUNTIME_WINDOWS_SIZE_MB",
        "RUNTIME_WINDOWS_PARTS",
    ):
        assert key in conf, "chiave mancante in install.conf: %s" % key
    assert conf["RUNTIME_WINDOWS_URL"].startswith("https://github.com/")
    assert int(conf["RUNTIME_WINDOWS_PARTS"]) >= 1


def test_update_install_conf_preserves_comments(tmp_path):
    path = tmp_path / "install.conf"
    path.write_text(
        "# commento da mantenere\nRUNTIME_WINDOWS_URL=vecchio\nRUNTIME_WINDOWS_SHA256=\n",
        encoding="utf-8",
    )
    asset.update_install_conf("https://example.test/runtime.zip", "abc123", 1234.0, 2, str(path))
    text = path.read_text(encoding="utf-8")
    assert "# commento da mantenere" in text
    conf = asset.parse_install_conf(str(path))
    assert conf["RUNTIME_WINDOWS_URL"] == "https://example.test/runtime.zip"
    assert conf["RUNTIME_WINDOWS_SHA256"] == "abc123"
    assert conf["RUNTIME_WINDOWS_SIZE_MB"] == "1234"
    assert conf["RUNTIME_WINDOWS_PARTS"] == "2"


def test_iter_runtime_files_skips_cache_and_dev(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / "Lib" / "site-packages" / "__pycache__").mkdir(parents=True)
    (runtime / "Lib" / "site-packages" / "__pycache__" / "x.pyc").write_bytes(b"x")
    (runtime / "Lib" / "site-packages" / "zz_dev_site_packages.pth").write_text("dev", encoding="utf-8")
    (runtime / "python.exe").write_bytes(b"MZ")
    (runtime / "Lib" / "module.py").write_text("x = 1\n", encoding="utf-8")
    files = {os.path.relpath(item, runtime).replace("\\", "/") for item in asset.iter_runtime_files(str(runtime))}
    assert "python.exe" in files
    assert "Lib/module.py" in files
    assert not any("__pycache__" in item for item in files)
    assert "Lib/site-packages/zz_dev_site_packages.pth" not in files


def test_split_archive_creates_parts_and_removes_original(tmp_path):
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(b"A" * (3 * 1024 * 1024))
    parts = asset.split_archive(str(archive), part_size_mb=1)
    assert len(parts) == 3
    assert not archive.exists()
    total = 0
    for part in parts:
        assert os.path.getsize(part) <= 1024 * 1024
        assert part.endswith((".001", ".002", ".003"))
        with open(part, "rb") as handle:
            total += len(handle.read())
    assert total == 3 * 1024 * 1024


def test_split_archive_keeps_small_file(tmp_path):
    archive = tmp_path / "small.zip"
    archive.write_bytes(b"B" * 1024)
    parts = asset.split_archive(str(archive), part_size_mb=1)
    assert parts == [str(archive)]
    assert archive.exists()


def test_check_repo_required_files_present():
    assert check_repo.check_required() == []


def test_check_repo_flags_local_paths():
    errors = check_repo.check_local_only(["runtime/Lib/site-packages/torch/__init__.py"])
    assert errors
    assert check_repo.check_local_only(["app/main.py"]) == []


def test_check_repo_detects_secret(tmp_path):
    sample = tmp_path / "config.py"
    sample.write_text('token = "sl.' + "A" * 60 + '"\n', encoding="utf-8")
    hits = check_repo.secret_hits([str(sample)])
    assert hits
    clean = tmp_path / "clean.py"
    clean.write_text("token = 'test-token'\n", encoding="utf-8")
    assert check_repo.secret_hits([str(clean)]) == []
