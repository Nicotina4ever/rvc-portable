"""Test dell'addestramento: dataset, preset, comandi, stato del servizio."""

from __future__ import annotations

import math
import os
import time
import wave

import pytest

from app.training import pipeline
from app.training.dataset import DatasetError, inspect_source, quick_check
from app.training.filelist import build_filelist
from app.training.manager import TrainingService, slugify
from app.training.presets import DEFAULT_PRESET, get_preset, preset_list


def _write_wav(path, seconds: float = 1.0, sample_rate: int = 16000):
    frames = int(seconds * sample_rate)
    payload = bytearray()
    for index in range(frames):
        value = int(6000 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
        payload += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return str(path)


def test_presets_are_consistent():
    presets = preset_list()
    assert {item["id"] for item in presets} == {"veloce", "bilanciato", "qualita"}
    default = get_preset(DEFAULT_PRESET)
    assert default.epochs >= 100
    assert get_preset("inesistente").id == DEFAULT_PRESET


def test_slugify_is_filename_safe():
    assert slugify("Voce di Nicola / test") == "Voce-di-Nicola-test"
    assert slugify("") == "modello"


def test_inspect_source_reports_short_dataset(tmp_path):
    folder = tmp_path / "dataset"
    folder.mkdir()
    _write_wav(folder / "uno.wav", seconds=1.0)
    _write_wav(folder / "due.wav", seconds=1.5)
    report = inspect_source(str(folder))
    assert report["files"] == 0  # sotto la soglia minima di 3 s per file
    assert report["ready"] is False
    assert report["errors"]


def test_inspect_source_accepts_audio(tmp_path):
    folder = tmp_path / "dataset"
    folder.mkdir()
    for index in range(3):
        _write_wav(folder / ("clip%d.wav" % index), seconds=4.0)
    report = inspect_source(str(folder))
    assert report["files"] == 3
    assert report["total_s"] == pytest.approx(12.0, abs=0.2)
    assert report["sample_rates"] == [16000]
    assert report["ready"] is False  # troppo corto in totale, ma i file sono validi


def test_quick_check_rejects_empty_folder(tmp_path):
    folder = tmp_path / "vuota"
    folder.mkdir()
    with pytest.raises(DatasetError):
        quick_check(str(folder))


def test_build_filelist_includes_mute(tmp_path):
    exp_dir = tmp_path / "exp"
    gt = exp_dir / "0_gt_wavs"
    feature = exp_dir / "3_feature768"
    f0_dir = exp_dir / "2a_f0"
    f0nsf = exp_dir / "2b-f0nsf"
    for directory in (gt, feature, f0_dir, f0nsf):
        directory.mkdir(parents=True)
    (gt / "a.wav").write_bytes(b"x")
    (feature / "a.npy").write_bytes(b"x")
    (f0_dir / "a.npy").write_bytes(b"x")
    (f0nsf / "a.npy").write_bytes(b"x")

    mute_dir = tmp_path / "mute"
    (mute_dir / "0_gt_wavs").mkdir(parents=True)
    (mute_dir / "3_feature768").mkdir(parents=True)
    (mute_dir / "2a_f0").mkdir(parents=True)
    (mute_dir / "2b-f0nsf").mkdir(parents=True)
    (mute_dir / "0_gt_wavs" / "mute48k.wav").write_bytes(b"x")
    (mute_dir / "3_feature768" / "mute.npy").write_bytes(b"x")
    (mute_dir / "2a_f0" / "mute.wav.npy").write_bytes(b"x")
    (mute_dir / "2b-f0nsf" / "mute.wav.npy").write_bytes(b"x")

    info = build_filelist(str(exp_dir), "v2", True, str(mute_dir), 48000)
    assert info["entries"] == 1
    assert info["mute"] == 2
    text = (exp_dir / "filelist.txt").read_text(encoding="utf-8")
    assert "|0" in text
    assert text.count("\n") >= 2


def test_build_command_train_has_core_flags(tmp_path):
    ctx = {
        "python": "python",
        "job_dir": str(tmp_path),
        "exp_dir": str(tmp_path / "logs" / "voce"),
        "exp_name": "voce",
        "raw_dir": str(tmp_path / "raw"),
        "settings": {
            "sample_rate": 48000,
            "version": "v2",
            "f0": True,
            "f0_method": "rmvpe",
            "epochs": 250,
            "batch_size": 6,
            "save_every": 20,
            "device": "cuda",
        },
        "pretrained_g": "G.pth",
        "pretrained_d": "D.pth",
        "nproc": 2,
    }
    command = pipeline.build_command("train", ctx)
    assert command[0] == "python"
    assert command[1].endswith("_boot.py")
    assert command[2] == "train.train"
    for flag in ("-te", "-bs", "-pg", "-pd", "-e", "-sr", "-v", "-f0"):
        assert flag in command
    assert command[command.index("-sr") + 1] == "48k"
    assert command[command.index("-e") + 1] == "voce"


def test_manager_fails_short_dataset(manager, paths, tmp_path):
    folder = tmp_path / "ds"
    folder.mkdir()
    for index in range(2):
        _write_wav(folder / ("clip%d.wav" % index), seconds=1.0)
    service = TrainingService(paths, manager)
    job = service.start({"source": str(folder), "name": "Test corto"})
    assert job["status"] in ("queued", "running")
    deadline = time.time() + 20
    while time.time() < deadline:
        current = service.get_job(job["id"])
        if current and current["status"] in ("failed", "completed", "canceled"):
            break
        time.sleep(0.1)
    current = service.get_job(job["id"])
    assert current is not None
    assert current["status"] == "failed"
    assert "dataset" in (current.get("error") or "").lower() or current["error"]


def test_manager_capabilities_without_gpu(manager, paths):
    service = TrainingService(paths, manager)
    caps = service.capabilities()
    assert caps["enabled"] is True
    assert "presets" in caps and len(caps["presets"]) == 3
    assert "assets" in caps
    assert os.path.isdir(paths.training_dir)


def test_training_settings_defaults(manager):
    settings = manager.load()
    assert settings.training.sample_rate == 48000
    assert settings.training.version == "v2"
    assert settings.training.f0 is True
    assert settings.training.epochs >= 100
    data = settings.public_dict()
    assert "training" in data
