"""Auto-test dei parametri RVC su un campione breve.

L'idea: prima di convertire un file intero, si converte un campione di ~10 s con
una piccola griglia di parametri e si sceglie la combinazione che misura meglio.
Le metriche sono oggettive e non richiedono un riferimento "ideale":

- **F0**: distanza in cents tra il contorno di intonazione atteso (input trasposto
  del pitch richiesto) e quello prodotto;
- **timbre**: rapporto tra i centroidi spettrali di output e input (un rapporto
  troppo basso e' il classico suono "voce chiusa / denti stretti");
- **articolazione**: energia relativa nella banda 4-8 kHz (consonanti e dettaglio);
- **voicing**: percentuale di frame sonori, per penalizzare output "soffiati";
- **clipping**: campioni saturi.

Il costo piu' basso vince. Il risultato include la classifica completa, cosi'
l'utente puo' ascoltare i candidati e cambiare scelta.
"""

from __future__ import annotations

import math
import os
import tempfile
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np

SAMPLE_SECONDS = 10.0
ANALYSIS_SR = 16000
F0_MIN = 50.0
F0_MAX = 1100.0


def _load_mono(path: str, sr: int = ANALYSIS_SR) -> np.ndarray:
    import librosa

    audio, _ = librosa.load(path, sr=sr, mono=True)
    return np.asarray(audio, dtype=np.float32)


def extract_sample(source: str, target: str, seconds: float = SAMPLE_SECONDS) -> str:
    """Estrae un campione dal centro del file (o dall'inizio se e' corto)."""
    import soundfile as sf

    try:
        data, rate = sf.read(source, dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
    except Exception:
        import librosa

        mono, rate = librosa.load(source, sr=None, mono=True)
    total = len(mono)
    wanted = int(max(1.0, float(seconds)) * rate)
    if total <= wanted:
        chunk = mono
    else:
        start = max(0, (total - wanted) // 2)
        chunk = mono[start : start + wanted]
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    sf.write(target, np.asarray(chunk, dtype=np.float32), rate, subtype="PCM_16")
    return target


def _f0_contour(audio: np.ndarray, sr: int = ANALYSIS_SR) -> np.ndarray:
    import parselmouth

    sound = parselmouth.Sound(np.asarray(audio, dtype=np.float64), sampling_frequency=sr)
    pitch = sound.to_pitch(time_step=0.01, pitch_floor=F0_MIN, pitch_ceiling=F0_MAX)
    return np.asarray(pitch.selected_array["frequency"], dtype=np.float32)


def _spectral_metrics(audio: np.ndarray, sr: int = ANALYSIS_SR) -> Dict[str, float]:
    import librosa

    centroid = librosa.feature.spectral_centroid(y=audio, sr=sr)
    spectrum = np.abs(librosa.stft(audio, n_fft=1024, hop_length=256))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    total = float(spectrum.sum()) + 1e-9
    hf_mask = (freqs >= 4000.0) & (freqs <= 8000.0)
    hf_ratio = float(spectrum[hf_mask].sum() / total)
    return {
        "centroid": float(np.median(centroid)) if centroid.size else 0.0,
        "hf_ratio": hf_ratio,
    }


def _resample_curve(values: np.ndarray, length: int) -> np.ndarray:
    if values.size == 0 or length <= 0:
        return np.zeros(length, dtype=np.float32)
    source = np.linspace(0.0, 1.0, num=values.size)
    target = np.linspace(0.0, 1.0, num=length)
    return np.interp(target, source, values).astype(np.float32)


def compare(source: str, output: str, pitch: int) -> Dict[str, Any]:
    """Confronta input e output; restituisce metriche e costo (piu' basso = meglio)."""
    src = _load_mono(source)
    out = _load_mono(output)
    frames = min(src.size, out.size)
    src, out = src[:frames], out[:frames]

    src_f0 = _f0_contour(src)
    out_f0 = _f0_contour(out)
    length = min(src_f0.size, out_f0.size)
    src_f0 = _resample_curve(src_f0[:length], length)
    out_f0 = _resample_curve(out_f0[:length], length)
    expected = src_f0 * (2.0 ** (float(pitch) / 12.0))
    voiced = (expected > 1.0) & (out_f0 > 1.0)
    if voiced.any():
        cents = 1200.0 * np.log2(np.maximum(out_f0[voiced], 1e-3) / np.maximum(expected[voiced], 1e-3))
        f0_rmse = float(np.sqrt(np.mean(np.square(cents))))
    else:
        f0_rmse = 600.0
    voiced_ratio = float((out_f0 > 1.0).mean()) / max(1e-6, float((src_f0 > 1.0).mean()))

    src_spec = _spectral_metrics(src)
    out_spec = _spectral_metrics(out)
    centroid_ratio = out_spec["centroid"] / max(1.0, src_spec["centroid"])
    hf_ratio = out_spec["hf_ratio"] / max(1e-6, src_spec["hf_ratio"])
    clipping = float(np.mean(np.abs(out) >= 0.995))

    cost = (
        (f0_rmse / 45.0) * 1.0
        + abs(math.log2(max(centroid_ratio, 1e-3))) * 2.2
        + abs(math.log2(max(hf_ratio, 1e-3))) * 2.0
        + abs(voiced_ratio - 1.0) * 2.5
        + clipping * 12.0
    )
    return {
        "cost": round(float(cost), 4),
        "score": round(float(max(0.0, 100.0 - cost * 6.0)), 1),
        "f0_rmse_cents": round(f0_rmse, 1),
        "centroid_ratio": round(float(centroid_ratio), 3),
        "hf_ratio": round(float(hf_ratio), 3),
        "voiced_ratio": round(float(voiced_ratio), 3),
        "clipping": round(clipping, 4),
    }


def candidate_grid(
    methods: Optional[Iterable[str]] = None,
    index_rates: Optional[Iterable[float]] = None,
    protects: Optional[Iterable[float]] = None,
) -> List[Dict[str, Any]]:
    methods = list(methods or ("rmvpe", "harvest"))
    index_rates = list(index_rates or (0.2, 0.45, 0.7))
    protects = list(protects or (0.2, 0.33, 0.5))
    candidates: List[Dict[str, Any]] = []
    for method in methods:
        for index_rate in index_rates:
            for protect in protects:
                candidates.append(
                    {
                        "method": method,
                        "index_rate": float(index_rate),
                        "protect": float(protect),
                    }
                )
    return candidates


def run_auto_tune(
    engine,
    input_path: str,
    base_params: Dict[str, Any],
    workdir: Optional[str] = None,
    seconds: float = SAMPLE_SECONDS,
    candidates: Optional[List[Dict[str, Any]]] = None,
    on_progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Converte un campione con ogni candidato e restituisce la classifica."""
    workdir = workdir or tempfile.mkdtemp(prefix="rvc-autotune-")
    os.makedirs(workdir, exist_ok=True)
    sample = extract_sample(input_path, os.path.join(workdir, "sample.wav"), seconds)
    grid = candidates or candidate_grid()
    results: List[Dict[str, Any]] = []
    total = len(grid)
    for position, candidate in enumerate(grid, start=1):
        params = dict(base_params)
        params.update(candidate)
        out_path = os.path.join(workdir, "cand_%02d.wav" % position)
        try:
            from app.core.engine import InferParams  # import locale: nessun costo all'avvio

            engine_params = InferParams(
                pitch=int(params.get("pitch", 0)),
                method=str(params["method"]),
                protect=float(params["protect"]),
                index_rate=float(params["index_rate"]),
                filter_radius=int(params.get("filter_radius", 3)),
                rms_mix_rate=float(params.get("rms_mix_rate", 0.25)),
                resample_sr=int(params.get("resample_sr", 0)),
                model_version=str(params.get("model_version", "v2")),
                output_format="wav",
            )
            engine.infer(sample, out_path, engine_params)
            if not os.path.isfile(out_path) or os.path.getsize(out_path) <= 44:
                raise RuntimeError("output vuoto")
            metrics = compare(sample, out_path, int(params.get("pitch", 0)))
            results.append({**candidate, **metrics, "output": out_path})
        except Exception as exc:  # tengo il candidato come fallito
            results.append({**candidate, "cost": 999.0, "score": 0.0, "error": str(exc)})
        if on_progress:
            on_progress(position, total, results[-1])
    results.sort(key=lambda item: item.get("cost", 999.0))
    best = results[0] if results else {}
    return {
        "sample": sample,
        "seconds": seconds,
        "grid_size": total,
        "results": results,
        "best": best,
        "workdir": workdir,
    }
