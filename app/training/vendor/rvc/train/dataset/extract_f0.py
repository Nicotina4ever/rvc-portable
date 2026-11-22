"""Estrazione F0 per il training RVC (rmvpe oppure parselmouth/pm).

Uso:
    python -m train.dataset.extract_f0 <exp_dir> <method> <device> <is_half>

Legge ``<exp_dir>/1_16k_wavs/*.wav`` e scrive:
    ``<exp_dir>/2a_f0/<nome>.wav.npy``     F0 quantizzata (1..255)
    ``<exp_dir>/2b-f0nsf/<nome>.wav.npy``  F0 continua in Hz
Stampa ``PROGRESS <fatti> <totali>`` per il backend.
"""

from __future__ import annotations

import os
import sys
import traceback

import numpy as np
from i18n.i18n import I18nAuto

i18n = I18nAuto()

F0_MIN = 50.0
F0_MAX = 1100.0
F0_MEL_MIN = 1127.0 * np.log(1.0 + F0_MIN / 700.0)
F0_MEL_MAX = 1127.0 * np.log(1.0 + F0_MAX / 700.0)
HOP_SAMPLES = 160


def coarse_f0(f0: np.ndarray):
    """Quantizzazione standard RVC: mel 50..1100 Hz -> interi 1..255."""
    f0 = np.asarray(f0, dtype=np.float32)
    f0_mel = 1127.0 * np.log(1.0 + f0 / 700.0)
    positive = f0_mel > 0
    f0_mel[positive] = (f0_mel[positive] - F0_MEL_MIN) / (F0_MEL_MAX - F0_MEL_MIN) * 254.0 + 1.0
    f0_mel[f0_mel <= 1] = 1
    f0_mel[f0_mel > 255] = 255
    f0_coarse = np.rint(f0_mel).astype(np.int32)
    return f0_coarse, f0


def _resolve_rmvpe_path() -> str:
    explicit = os.environ.get("RVC_RMVPE_PATH", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    try:
        import rvc_python

        candidate = os.path.join(
            os.path.dirname(os.path.abspath(rvc_python.__file__)),
            "base_model",
            "rmvpe.pt",
        )
        if os.path.isfile(candidate):
            return candidate
    except Exception:
        pass
    raise FileNotFoundError(
        "rmvpe.pt non trovato: imposta RVC_RMVPE_PATH o installa rvc_python"
    )


def _pm_f0(path: str) -> np.ndarray:
    import parselmouth

    sound = parselmouth.Sound(path)
    pitch = sound.to_pitch(time_step=HOP_SAMPLES / 16000.0, pitch_floor=F0_MIN, pitch_ceiling=F0_MAX)
    return np.asarray(pitch.selected_array["frequency"], dtype=np.float32)


class _RmvpeExtractor:
    def __init__(self, device: str, is_half: bool):
        from infer.rmvpe import RMVPE

        self.model = RMVPE(_resolve_rmvpe_path(), is_half=is_half, device=device)

    def __call__(self, path: str) -> np.ndarray:
        import librosa

        audio, _sr = librosa.load(path, sr=16000, mono=True)
        return np.asarray(self.model.infer_from_audio(audio, thred=0.03), dtype=np.float32)


def main(argv):
    if len(argv) < 5:
        print("usage: extract_f0 <exp_dir> <method> <device> <is_half>")
        return 2
    exp_dir = argv[1]
    method = argv[2].strip().lower()
    device = argv[3]
    is_half = argv[4].strip().lower() == "true"
    if method not in ("rmvpe", "pm"):
        print("metodo F0 non supportato: %s" % method)
        return 2

    src_dir = os.path.join(exp_dir, "1_16k_wavs")
    out_coarse = os.path.join(exp_dir, "2a_f0")
    out_float = os.path.join(exp_dir, "2b-f0nsf")
    os.makedirs(out_coarse, exist_ok=True)
    os.makedirs(out_float, exist_ok=True)

    names = sorted(name for name in os.listdir(src_dir) if name.lower().endswith(".wav"))
    total = len(names)
    if total == 0:
        print("nessun file in %s" % src_dir)
        return 1

    extractor = _RmvpeExtractor(device, is_half) if method == "rmvpe" else _pm_f0
    done = 0
    failed = 0
    for name in names:
        base = os.path.splitext(name)[0]
        coarse_path = os.path.join(out_coarse, "%s.npy" % base)
        float_path = os.path.join(out_float, "%s.npy" % base)
        if os.path.isfile(coarse_path) and os.path.isfile(float_path):
            done += 1
            print("PROGRESS %d %d" % (done, total), flush=True)
            continue
        try:
            f0 = extractor(os.path.join(src_dir, name))
            if f0 is None or len(f0) == 0:
                raise ValueError("F0 vuoto")
            f0 = np.nan_to_num(np.asarray(f0, dtype=np.float32), nan=0.0)
            coarse, continuous = coarse_f0(f0)
            np.save(coarse_path, coarse)
            np.save(float_path, continuous)
            done += 1
        except Exception:
            failed += 1
            print("FAILED %s" % name, flush=True)
            print(traceback.format_exc(), flush=True)
        print("PROGRESS %d %d" % (done + failed, total), flush=True)

    print("DONE f0 ok=%d failed=%d" % (done, failed), flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
