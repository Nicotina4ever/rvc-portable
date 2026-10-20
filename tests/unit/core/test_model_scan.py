"""Test di ``app.core.model_scan``: coppie pth/index, warning, limiti di ricorsione."""

from __future__ import annotations

import os

from app.core.model_scan import guess_version, scan_models


def _touch(path, data: bytes = b"x" * 1024):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return str(path)


def _by_name(result):
    return {entry["name"]: entry for entry in result["models"]}


def test_pairs_models_with_indexes(tmp_path):
    root = tmp_path / "Modelli"
    _touch(root / "Nicola-Spot2.pth", b"x" * (2 * 1024 * 1024))
    _touch(root / "added_IVF1456_Flat_nprobe_1_Nicola-Spot2_v2.index")
    _touch(root / "Nicola-Narra.pth")
    _touch(root / "trained_IVF256_Flat_nprobe_1_Nicola-Narra_v2.index")
    result = scan_models([str(root)])
    models = _by_name(result)
    assert set(models) == {"Nicola-Spot2", "Nicola-Narra"}
    spot = models["Nicola-Spot2"]
    assert spot["has_index"] is True
    assert os.path.basename(spot["index_path"]).startswith("added_")
    assert spot["warnings"] == []
    assert spot["version_guess"] == "v2"
    assert spot["size_mb"] == 2.0
    assert spot["source"] == "Modelli"
    narra = models["Nicola-Narra"]
    assert not os.path.basename(narra["index_path"]).startswith("added_")


def test_added_and_trained_variants_are_not_ambiguous(tmp_path):
    root = tmp_path / "Modelli"
    _touch(root / "voice.pth")
    _touch(root / "added_IVF8_Flat_nprobe_1_voice_v2.index")
    _touch(root / "trained_IVF8_Flat_nprobe_1_voice_v2.index")
    models = _by_name(scan_models([str(root)]))
    entry = models["voice"]
    assert os.path.basename(entry["index_path"]).startswith("added_")
    assert entry["warnings"] == []


def test_missing_index_warning(tmp_path):
    root = tmp_path / "Modelli"
    _touch(root / "senza-indice.pth")
    entry = _by_name(scan_models([str(root)]))["senza-indice"]
    assert entry["has_index"] is False
    assert entry["index_path"] == ""
    assert any("indice" in warning for warning in entry["warnings"])


def test_recursion_is_limited_to_two_levels(tmp_path):
    root = tmp_path / "Modelli"
    _touch(root / "top.pth")
    _touch(root / "sub" / "mid.pth")
    _touch(root / "sub" / "deeper" / "deep.pth")
    _touch(root / "sub" / "deeper" / "too-deep" / "hidden.pth")
    models = _by_name(scan_models([str(root)]))
    assert "top" in models
    assert "mid" in models
    assert "deep" in models
    assert "hidden" not in models


def test_version_guess_from_name(tmp_path):
    assert guess_version("voice_v1.pth") == "v1"
    assert guess_version("voice-V1.pth") == "v1"
    assert guess_version("voice_v2.pth") == "v2"
    assert guess_version("Nicola-Spot2.pth") == "v2"
    assert guess_version("whatever.pth") == "v2"


def test_default_index_hint_used_when_name_matches(tmp_path):
    root = tmp_path / "Modelli"
    _touch(root / "voice.pth")
    hint = _touch(tmp_path / "cache" / "added_IVF1_Flat_nprobe_1_voice_v2.index")
    result = scan_models([str(root)], default_index_hint=hint)
    entry = _by_name(result)["voice"]
    assert entry["index_path"] == os.path.abspath(hint)
    assert any("predefinito" in warning for warning in entry["warnings"])


def test_scan_never_modifies_files(tmp_path):
    root = tmp_path / "Modelli"
    model = _touch(root / "voice.pth", b"model-bytes")
    index = _touch(root / "added_voice.index", b"index-bytes")
    before = {
        path: (os.stat(path).st_size, os.stat(path).st_mtime_ns)
        for path in (model, index)
    }
    scan_models([str(root)])
    after = {
        path: (os.stat(path).st_size, os.stat(path).st_mtime_ns)
        for path in (model, index)
    }
    assert before == after


def test_missing_root_warns(tmp_path):
    result = scan_models([str(tmp_path / "non-esiste")])
    assert result["models"] == []
    assert any("non trovata" in warning for warning in result["warnings"])


def test_multiple_roots_and_duplicates(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _touch(root_a / "uno.pth")
    _touch(root_b / "due.pth")
    result = scan_models([str(root_a), str(root_b)])
    names = {entry["name"] for entry in result["models"]}
    assert names == {"uno", "due"}
    assert len(result["roots"]) == 2


def test_default_root_used_when_none(tmp_path, monkeypatch):
    models_dir = tmp_path / "Modelli"
    _touch(models_dir / "default.pth")
    monkeypatch.setattr(
        "app.core.model_scan.default_models_root", lambda: str(models_dir)
    )
    result = scan_models()
    assert [entry["name"] for entry in result["models"]] == ["default"]
