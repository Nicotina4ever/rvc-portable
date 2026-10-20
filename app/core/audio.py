"""Utility audio del backend: waveform per la UI e probe metadati.

Contratto (docs/API-CONTRACT.md):

- ``waveform_peaks(path, buckets=800)`` -> ``{"peaks": [0..1], "duration_s", "sample_rate"}``
- ``probe_audio(path)`` -> ``{"duration_s", "sample_rate", "channels", "format"}``

Scelte implementative:

- ``soundfile`` (libsndfile) e' il decoder principale (WAV/FLAC/OGG/MP3);
  per i formati che libsndfile non apre (m4a/aac/opus/wma) si usa PyAV, gia'
  presente nel runtime del motore. **Nessuna dipendenza nuova.**
- i picchi sono calcolati a blocchi (memoria costante) e normalizzati in
  ``0..1`` rispetto al picco massimo del file; un file silenzioso produce
  ``[0.0] * buckets``.
- cache su disco in ``<root>/data/cache/waveforms`` (override con la variabile
  d'ambiente ``RVC_WAVEFORM_CACHE``), invalidata da ``mtime``/dimensione.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger("rvc.audio")

BLOCK_FRAMES = 65536
MAX_BUCKETS = 20000
CACHE_ENV = "RVC_WAVEFORM_CACHE"
CACHE_VERSION = 1

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def cache_root() -> str:
    override = (os.environ.get(CACHE_ENV) or "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(_PROJECT_ROOT, "data", "cache", "waveforms")


def waveform_peaks(path: str, buckets: int = 800) -> Dict[str, Any]:
    """Picchi normalizzati (uno per bucket) per disegnare la waveform."""
    buckets = _validate_buckets(buckets)
    source = _existing_file(path)
    cached = _read_cache(source, buckets)
    if cached is not None:
        return cached

    peaks, duration_s, sample_rate = _compute_peaks(source, buckets)
    result = {
        "peaks": peaks,
        "duration_s": round(float(duration_s), 3),
        "sample_rate": int(sample_rate or 0),
    }
    _write_cache(source, buckets, result)
    return result


def probe_audio(path: str) -> Dict[str, Any]:
    """Metadati audio (durata, sample rate, canali, formato)."""
    source = _existing_file(path)
    try:
        import soundfile as sf  # import locale: backend leggero all'avvio

        info = sf.info(source)
        return {
            "duration_s": round(float(info.duration), 3),
            "sample_rate": int(info.samplerate),
            "channels": int(info.channels),
            "format": str(info.format or "").strip() or "unknown",
        }
    except Exception as exc:  # libsndfile non apre il formato: prova PyAV
        LOGGER.debug("soundfile non decodifica %s: %s", source, exc)

    try:
        decoded, sample_rate, channels = _decode_with_av(source)
    except Exception as exc:
        raise ValueError(
            "formato audio non supportato o file corrotto: %s (%s)" % (source, exc)
        ) from exc
    frames = int(decoded.shape[0])
    duration = float(frames) / float(sample_rate) if sample_rate else 0.0
    return {
        "duration_s": round(duration, 3),
        "sample_rate": int(sample_rate),
        "channels": int(channels),
        "format": _av_format(source),
    }


# ---------------------------------------------------------------------------
# Implementazione
# ---------------------------------------------------------------------------


def _validate_buckets(buckets: Any) -> int:
    try:
        value = int(buckets)
    except (TypeError, ValueError):
        raise ValueError("buckets non valido: %r" % (buckets,)) from None
    if value < 1:
        raise ValueError("buckets deve essere >= 1")
    return min(value, MAX_BUCKETS)


def _existing_file(path: str) -> str:
    if not path:
        raise FileNotFoundError("percorso audio vuoto")
    source = os.path.abspath(os.path.expanduser(str(path).strip().strip('"')))
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    return source


def _compute_peaks(source: str, buckets: int):
    try:
        return _peaks_with_soundfile(source, buckets)
    except Exception as exc:
        LOGGER.debug("soundfile non decodifica %s: %s", source, exc)
    try:
        return _peaks_with_pyav(source, buckets)
    except Exception as exc:
        raise ValueError(
            "formato audio non supportato o file corrotto: %s (%s)" % (source, exc)
        ) from exc


def _peaks_with_soundfile(source: str, buckets: int):
    import numpy as np
    import soundfile as sf

    peaks = None
    total_frames = 0
    position = 0
    sample_rate = 0
    channels = 0
    with sf.SoundFile(source) as handle:
        sample_rate = int(handle.samplerate)
        total_frames = int(handle.frames)
        channels = int(handle.channels)
        if total_frames <= 0 or sample_rate <= 0:
            return [0.0] * buckets, 0.0, sample_rate or 0
        peaks = np.zeros(buckets, dtype=np.int32)
        for block in handle.blocks(blocksize=BLOCK_FRAMES, dtype="int16", always_2d=True):
            if block.size == 0:
                continue
            values = np.max(np.abs(block.astype(np.int32)), axis=1)
            indices = (
                np.arange(position, position + values.shape[0], dtype=np.int64)
                * buckets
            ) // total_frames
            np.maximum.at(peaks, np.clip(indices, 0, buckets - 1), values)
            position += values.shape[0]
    if peaks is None or position <= 0:
        return [0.0] * buckets, 0.0, sample_rate or 0

    normalized = peaks.astype(np.float32) / 32768.0
    return _finalize_peaks(normalized, position, sample_rate, channels)


def _peaks_with_pyav(source: str, buckets: int):
    import numpy as np

    decoded, sample_rate, channels = _decode_with_av(source)
    total_frames = int(decoded.shape[0])
    if total_frames <= 0 or sample_rate <= 0:
        return [0.0] * buckets, 0.0, sample_rate or 0
    frames = np.abs(decoded)
    indices = (np.arange(total_frames, dtype=np.int64) * buckets) // total_frames
    peaks = np.zeros(buckets, dtype=np.float32)
    np.maximum.at(peaks, np.clip(indices, 0, buckets - 1), frames)
    return _finalize_peaks(peaks, total_frames, sample_rate, channels)


def _finalize_peaks(values, total_frames: int, sample_rate: int, channels: int):
    max_peak = float(values.max()) if values.size else 0.0
    if max_peak > 0:
        values = values / max_peak
    peaks = [round(min(1.0, max(0.0, float(value))), 4) for value in values]
    duration = float(total_frames) / float(sample_rate)
    return peaks, duration, sample_rate


def _decode_with_av(source: str):
    """Decodifica completa con PyAV (fallback formati compressi)."""
    import av
    import numpy as np

    chunks: List[Any] = []
    sample_rate = 0
    channels = 0
    with av.open(source) as container:
        stream = next(
            (item for item in container.streams if item.type == "audio"), None
        )
        if stream is None:
            raise ValueError("nessun flusso audio nel file")
        sample_rate = int(stream.rate or (stream.codec_context and stream.codec_context.sample_rate) or 0)
        channels = int(stream.channels or 0)
        for frame in container.decode(stream):
            array = frame.to_ndarray()
            if array.ndim == 2:
                # PyAV: (channels, frames); portiamo a (frames, channels)
                array = array.reshape(-1, array.shape[-1]).T
                if not channels:
                    channels = int(array.shape[1])
            else:
                array = array.reshape(-1, 1)
                if not channels:
                    channels = 1
            if array.dtype.kind in ("i", "u"):
                scale = float(1 << (8 * array.dtype.itemsize - 1))
                array = array.astype(np.float32) / scale
            else:
                array = array.astype(np.float32)
            if not sample_rate:
                sample_rate = int(frame.sample_rate or 0)
            chunks.append(np.abs(array))
    if not chunks:
        raise ValueError("file audio vuoto")
    stacked = np.concatenate(chunks, axis=0)
    if stacked.ndim == 2 and stacked.shape[1] > 1:
        stacked = np.max(stacked, axis=1)
    else:
        stacked = stacked.reshape(-1)
    return stacked, sample_rate, max(1, channels)


def _av_format(source: str) -> str:
    try:
        import av

        with av.open(source) as container:
            name = getattr(container.format, "name", "")
            return str(name or "unknown").split(",")[0]
    except Exception:  # pragma: no cover
        return "unknown"


# ---------------------------------------------------------------------------
# Cache su disco
# ---------------------------------------------------------------------------


def _cache_key(source: str, buckets: int) -> Optional[str]:
    try:
        stat = os.stat(source)
    except OSError:
        return None
    raw = "%s|%d|%d|%d" % (
        os.path.normcase(source),
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
        int(buckets),
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_path(source: str, buckets: int) -> Optional[str]:
    key = _cache_key(source, buckets)
    if not key:
        return None
    return os.path.join(cache_root(), key + ".json")


def _read_cache(source: str, buckets: int) -> Optional[Dict[str, Any]]:
    path = _cache_path(source, buckets)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    if int(data.get("buckets", 0)) != buckets:
        return None
    peaks = data.get("peaks")
    if not isinstance(peaks, list) or len(peaks) != buckets:
        return None
    try:
        return {
            "peaks": [float(value) for value in peaks],
            "duration_s": round(float(data.get("duration_s", 0.0)), 3),
            "sample_rate": int(data.get("sample_rate", 0)),
        }
    except (TypeError, ValueError):
        return None


def _write_cache(source: str, buckets: int, result: Dict[str, Any]) -> None:
    path = _cache_path(source, buckets)
    if not path:
        return
    payload = {
        "version": CACHE_VERSION,
        "buckets": buckets,
        "path": source,
        "peaks": result["peaks"],
        "duration_s": result["duration_s"],
        "sample_rate": result["sample_rate"],
        "cached_at": time.time(),
    }
    tmp = ""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".waveform-", suffix=".tmp", dir=os.path.dirname(path)
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as exc:  # cache non essenziale: non bloccare la UI
        LOGGER.debug("cache waveform non scrivibile (%s): %s", path, exc)
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def clear_cache() -> int:
    """Svuota la cache waveform (usata da strumenti/test)."""
    root = cache_root()
    removed = 0
    try:
        for name in os.listdir(root):
            if not name.endswith(".json"):
                continue
            try:
                os.remove(os.path.join(root, name))
                removed += 1
            except OSError:
                pass
    except OSError:
        return removed
    return removed
