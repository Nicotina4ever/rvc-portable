"""Estrazione feature HuBERT per il training RVC.

Uso:
    python -m train.dataset.extract_hubert_feature <exp_dir> <version> <device> <is_half>

Legge ``<exp_dir>/1_16k_wavs/*.wav`` e scrive
``<exp_dir>/3_feature256|768/<nome>.npy`` con forma ``(frame, dim)``.
Stampa ``PROGRESS <fatti> <totali>`` per il backend.
"""

from __future__ import annotations

import os
import sys
import traceback

import numpy as np
import torch
from configs.config import get_device_dtype_sm
from i18n.i18n import I18nAuto
from infer.hubert import extract_hubert_features, load_hubert_model

i18n = I18nAuto()


def main(argv):
    if len(argv) < 5:
        print("usage: extract_hubert_feature <exp_dir> <version> <device> <is_half>")
        return 2
    exp_dir = argv[1]
    version = argv[2].strip().lower()
    device = argv[3]
    is_half = argv[4].strip().lower() == "true"
    if version not in ("v1", "v2"):
        print("versione non supportata: %s" % version)
        return 2

    if device.startswith("cuda") and torch.cuda.is_available():
        selected, dtype, _sm, _mem = get_device_dtype_sm(0)
        if selected.type == "cuda":
            device = str(selected)
            is_half = is_half and dtype == torch.float16
    elif device.startswith("cuda"):
        device = "cpu"
        is_half = False

    src_dir = os.path.join(exp_dir, "1_16k_wavs")
    feature_dir = os.path.join(exp_dir, "3_feature256" if version == "v1" else "3_feature768")
    os.makedirs(feature_dir, exist_ok=True)

    names = sorted(name for name in os.listdir(src_dir) if name.lower().endswith(".wav"))
    total = len(names)
    if total == 0:
        print("nessun file in %s" % src_dir)
        return 1

    model = load_hubert_model(device, is_half=is_half)
    done = 0
    failed = 0
    for name in names:
        base = os.path.splitext(name)[0]
        target = os.path.join(feature_dir, "%s.npy" % base)
        if os.path.isfile(target):
            done += 1
            print("PROGRESS %d %d" % (done, total), flush=True)
            continue
        try:
            import soundfile as sf

            audio, sr = sf.read(os.path.join(src_dir, name), dtype="float32", always_2d=True)
            if sr != 16000:
                import librosa

                audio = librosa.resample(audio.mean(axis=1), orig_sr=sr, target_sr=16000)
            else:
                audio = audio.mean(axis=1)
            feats = extract_hubert_features(
                model, audio, version=version, device=device, is_half=is_half
            )
            if feats.size == 0:
                raise ValueError("feature vuote")
            assert np.isnan(feats).sum() == 0, "NaN nelle feature"
            np.save(target, feats)
            done += 1
        except Exception:
            failed += 1
            print("FAILED %s" % name, flush=True)
            print(traceback.format_exc(), flush=True)
        print("PROGRESS %d %d" % (done + failed, total), flush=True)

    print("DONE hubert ok=%d failed=%d" % (done, failed), flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
