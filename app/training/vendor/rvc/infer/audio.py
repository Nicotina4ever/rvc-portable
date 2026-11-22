"""Caricamento audio per il training, senza dipendenze ffmpeg esterne.

Usa ``soundfile`` (libsndfile) come primo decoder e PyAV come fallback per i
formati che libsndfile non apre (m4a/aac/opus). Restituisce sempre float32 mono
alla frequenza richiesta.
"""

from __future__ import annotations

import os

import numpy as np

AUDIO_LOAD_BACKEND = "soundfile+av"


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples
    try:
        import librosa

        return librosa.resample(
            samples, orig_sr=source_rate, target_sr=target_rate
        ).astype(np.float32)
    except Exception:
        from scipy.signal import resample_poly

        divisor = int(np.gcd(int(source_rate), int(target_rate)))
        return resample_poly(
            samples, int(target_rate) // divisor, int(source_rate) // divisor
        ).astype(np.float32)


def _load_with_soundfile(path: str, rate: int):
    import soundfile as sf

    data, source_rate = sf.read(path, dtype="float32", always_2d=True)
    if data.size == 0:
        return None
    mono = data.mean(axis=1)
    return _resample(mono, int(source_rate), int(rate))


def _load_with_av(path: str, rate: int):
    import av

    container = av.open(path)
    try:
        stream = next(s for s in container.streams if s.type == "audio")
        try:
            stream.thread_type = "AUTO"
        except Exception:
            pass
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=int(rate))
        chunks = []
        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                chunks.append(converted.to_ndarray().reshape(-1))
        for converted in resampler.resample(None):
            chunks.append(converted.to_ndarray().reshape(-1))
    finally:
        container.close()
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32)


def load_audio(file, sr):
    """Carica ``file`` come mono float32 a ``sr`` Hz (API compatibile RVC)."""
    path = str(file)
    if not os.path.isfile(path):
        raise FileNotFoundError("audio non trovato: %s" % path)
    rate = int(sr)

    # I WAV 16-bit/24-bit sono il caso normale: libsndfile e' il piu' veloce.
    if path.lower().endswith((".wav", ".flac", ".ogg", ".aiff", ".aif")):
        try:
            loaded = _load_with_soundfile(path, rate)
            if loaded is not None:
                return loaded
        except Exception:
            pass

    try:
        loaded = _load_with_soundfile(path, rate)
        if loaded is not None:
            return loaded
    except Exception:
        pass
    return _load_with_av(path, rate)
