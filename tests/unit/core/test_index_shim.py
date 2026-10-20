"""Test di ``app.core.index_shim``: alias trained_* -> added_* senza toccare l'originale."""

from __future__ import annotations

import os

import pytest

from app.core.index_shim import resolved_index_path


def _write(path, data: bytes = b"index-data"):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def test_empty_path_returns_empty(tmp_path):
    assert resolved_index_path("", str(tmp_path / "cache")) == ""


def test_path_without_trained_is_unchanged(tmp_path):
    index = _write(tmp_path / "models" / "added_IVF1_Flat_nprobe_1_voice_v2.index")
    assert resolved_index_path(index, str(tmp_path / "cache")) == os.path.abspath(index)


def test_sibling_added_preferred(tmp_path):
    original = _write(tmp_path / "models" / "trained_IVF1_Flat_nprobe_1_voice_v2.index")
    sibling = _write(tmp_path / "models" / "added_IVF1_Flat_nprobe_1_voice_v2.index", b"sibling")
    resolved = resolved_index_path(original, str(tmp_path / "cache"))
    assert resolved == os.path.abspath(sibling)
    with open(resolved, "rb") as handle:
        assert handle.read() == b"sibling"


def test_alias_created_in_cache_when_missing(tmp_path):
    models = tmp_path / "models"
    original = _write(models / "trained_IVF2_Flat_nprobe_1_voice_v2.index", b"trained-bytes")
    cache = tmp_path / "cache"
    resolved = resolved_index_path(original, str(cache))
    assert resolved != str(original)
    assert os.path.isfile(resolved)
    assert "added" in os.path.basename(resolved)
    with open(resolved, "rb") as handle:
        assert handle.read() == b"trained-bytes"
    # L'originale non viene modificato ne' duplicato accanto al modello.
    assert sorted(os.listdir(models)) == ["trained_IVF2_Flat_nprobe_1_voice_v2.index"]


def test_alias_is_stable_and_cached(tmp_path):
    original = _write(tmp_path / "models" / "trained_voice.index", b"abc")
    cache = tmp_path / "cache"
    first = resolved_index_path(original, str(cache))
    second = resolved_index_path(original, str(cache))
    assert first == second
    aliases = os.listdir(os.path.join(cache, "indices"))
    assert len([name for name in aliases if name.endswith(".index")]) == 1


def test_alias_regenerated_when_source_replaced(tmp_path):
    models = tmp_path / "models"
    original = _write(models / "trained_voice.index", b"old")
    cache = tmp_path / "cache"
    first = resolved_index_path(original, str(cache))
    replaced = models / "trained_voice.index.new"
    replaced.write_bytes(b"new-and-longer")
    os.replace(replaced, original)
    second = resolved_index_path(original, str(cache))
    with open(second, "rb") as handle:
        assert handle.read() == b"new-and-longer"
    assert first == second


def test_missing_index_returns_input(tmp_path):
    missing = str(tmp_path / "models" / "trained_missing.index")
    assert resolved_index_path(missing, str(tmp_path / "cache")) == missing


@pytest.mark.parametrize("cache_dir", ["", None])
def test_no_cache_dir_returns_original_path(tmp_path, cache_dir):
    original = _write(tmp_path / "models" / "trained_voice.index")
    assert resolved_index_path(original, cache_dir or "") == os.path.abspath(original)
