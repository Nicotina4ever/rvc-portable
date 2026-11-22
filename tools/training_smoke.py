"""Smoke test manuale della pipeline di training (non fa parte della suite)."""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = r"K:\AI\rvc-portable"
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.paths import AppPaths  # noqa: E402
from app.settings import SettingsManager  # noqa: E402
from app.training import assets, pipeline  # noqa: E402
from app.training.filelist import build_filelist  # noqa: E402

JOB = os.path.join(ROOT, "data", "training", "_smoke")
RAW = os.path.join(JOB, "dataset", "raw")
EXP = os.path.join(JOB, "logs", "smoke")
for folder in (RAW, EXP, os.path.join(JOB, "weights"), os.path.join(JOB, "output")):
    os.makedirs(folder, exist_ok=True)

paths = AppPaths.create()
manager = SettingsManager(paths)
manager.load()
settings = manager.settings

# Dataset sintetico: 3 clip da 12 s a 48 kHz.
if not any(name.endswith(".wav") for name in os.listdir(RAW)):
    for index in range(3):
        sr = 48000
        t = np.arange(int(12 * sr)) / sr
        signal = 0.2 * np.sin(2 * np.pi * (180 + index * 40) * t)
        sf.write(os.path.join(RAW, "clip%d.wav" % index), signal.astype(np.float32), sr)
print("dataset:", os.listdir(RAW))

job_settings = {
    "sample_rate": 48000,
    "version": "v2",
    "f0": True,
    "f0_method": "rmvpe",
    "epochs": 1,
    "batch_size": 2,
    "save_every": 1,
    "device": "cuda",
}

info = assets.ensure_pretrained(
    paths, settings, 48000, True, "v2", on_log=lambda message: print("ASSET", message)
)
print("pretrained:", json.dumps(info["found"], indent=2))
if not info["complete"]:
    raise SystemExit("pretrained mancanti: %s" % info["missing"])

hubert = assets.resolve_runtime_model("hubert_base.pt", paths)
rmvpe = assets.resolve_runtime_model("rmvpe.pt", paths)
print("hubert:", hubert)
print("rmvpe:", rmvpe)

# config esperimento
template = os.path.join(pipeline.VENDOR_ROOT, "configs", "v2", "48k.json")
with open(template, encoding="utf-8") as handle:
    config = json.load(handle)
config["train"]["batch_size"] = 2
with open(os.path.join(EXP, "config.json"), "w", encoding="utf-8") as handle:
    json.dump(config, handle, indent=4)

env = pipeline.build_env(paths, JOB, EXP, {"hubert": hubert, "rmvpe": rmvpe}, 2)
ctx = {
    "python": pipeline.resolve_python(paths),
    "job_dir": JOB,
    "exp_dir": EXP,
    "exp_name": "smoke",
    "raw_dir": RAW,
    "settings": job_settings,
    "pretrained_g": info["found"]["g"],
    "pretrained_d": info["found"]["d"],
    "nproc": 2,
}
log_path = os.path.join(JOB, "log.txt")


def run(stage: str) -> None:
    started = time.time()
    print("=== %s ===" % stage, flush=True)
    command = pipeline.build_command(stage, ctx)
    print("cmd:", " ".join(command), flush=True)
    code = pipeline.run_stage(
        command,
        cwd=JOB,
        env=env,
        log_path=log_path,
        on_line=lambda line: print("  " + line, flush=True)
        if any(token in line for token in ("PROGRESS", "RVC_", "loss_gen", "Error", "error", "Traceback"))
        else None,
        timeout_s=1800,
    )
    print("exit=%s in %.1fs" % (code, time.time() - started), flush=True)
    if code != 0:
        raise SystemExit("stadio %s fallito" % stage)


run("preprocess")
run("f0")
print("filelist:", build_filelist(EXP, "v2", True, pipeline.MUTE_DIR, 48000))
run("hubert")
run("train")
run("index")
print("SMOKE OK")
print("weights:", os.listdir(os.path.join(JOB, "weights")))
print("output:", os.listdir(os.path.join(JOB, "output")))
