"""Import e analisi del dataset di addestramento.

Obiettivo: dire subito all'utente se il dataset e' utilizzabile, senza avviare
GPU o processi lunghi. Supporta una cartella, uno ZIP o un singolo file audio.
Non modifica mai la sorgente: copia (o estrae) in ``data/training/jobs/<id>/dataset/raw``.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import zipfile
from typing import Any, Dict, List, Tuple

AUDIO_EXTENSIONS = (
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".opus",
    ".m4a",
    ".aac",
    ".wma",
    ".aiff",
    ".aif",
)

MIN_FILE_SECONDS = 3.0
MIN_TOTAL_SECONDS = 480.0
GOOD_TOTAL_SECONDS = 900.0
MAX_FILES = 2000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
ZIP_MAX_ENTRIES = 3000


class DatasetError(ValueError):
    """Errore leggibile sull'import del dataset."""


def _is_audio(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS


def _safe_name(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/"))
    cleaned = "".join(
        char if (char.isalnum() or char in "._- ") else "_" for char in base
    ).strip()
    return cleaned or "audio.wav"


def _probe_path(path: str) -> Tuple[float, int, int]:
    """Ritorna (durata_s, sample_rate, canali); solleva DatasetError se illeggibile."""
    try:
        import soundfile as sf

        info = sf.info(path)
        if info.frames and info.samplerate:
            return (
                float(info.frames) / float(info.samplerate),
                int(info.samplerate),
                int(info.channels or 1),
            )
    except Exception:
        pass
    try:
        import av

        with av.open(path) as container:
            stream = next(s for s in container.streams if s.type == "audio")
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            else:
                duration = 0.0
            rate = int(stream.rate or 0)
            channels = int(stream.channels or 1)
        if duration > 0 and rate > 0:
            return duration, rate, channels
    except Exception as exc:
        raise DatasetError("file audio illeggibile: %s (%s)" % (path, exc))
    raise DatasetError("file audio senza durata valida: %s" % path)


def _probe_bytes(name: str, data: bytes) -> Tuple[float, int, int]:
    try:
        import soundfile as sf

        with sf.SoundFile(io.BytesIO(data)) as handle:
            frames = int(handle.frames)
            rate = int(handle.samplerate)
            channels = int(handle.channels or 1)
        if frames and rate:
            return float(frames) / float(rate), rate, channels
    except Exception:
        pass
    # Fallback: file temporaneo + PyAV.
    import tempfile

    suffix = os.path.splitext(name)[1] or ".bin"
    handle, tmp = tempfile.mkstemp(prefix="rvc-ds-", suffix=suffix)
    os.close(handle)
    try:
        with open(tmp, "wb") as out:
            out.write(data)
        return _probe_path(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _verdict(report: Dict[str, Any]) -> Dict[str, Any]:
    total = float(report.get("total_s") or 0.0)
    files = int(report.get("files") or 0)
    warnings: List[str] = list(report.get("warnings") or [])
    errors: List[str] = list(report.get("errors") or [])
    ready = True
    if files == 0:
        ready = False
        errors.append("Nessun file audio valido trovato.")
    elif files < 3:
        warnings.append("Meno di 3 file: il modello avra' poco materiale.")
    if total < MIN_TOTAL_SECONDS:
        ready = False
        errors.append(
            "Servono almeno 8 minuti di audio (trovati %.1f min)." % (total / 60.0)
        )
    elif total < GOOD_TOTAL_SECONDS:
        warnings.append(
            "Dataset corto (%.1f min): qualita' limitata, meglio 15-30 minuti."
            % (total / 60.0)
        )
    if total > 3600:
        warnings.append("Dataset molto lungo: il training puo' durare alcune ore.")
    report["warnings"] = warnings
    report["errors"] = errors
    report["ready"] = ready and not errors
    return report


def inspect_source(source: str) -> Dict[str, Any]:
    """Analizza cartella/ZIP/file senza copiare nulla."""
    path = os.path.abspath(str(source or "").strip())
    if not os.path.exists(path):
        raise DatasetError("percorso dataset non trovato: %s" % path)
    entries: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings: List[str] = []

    if os.path.isfile(path) and path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if len(names) > ZIP_MAX_ENTRIES:
                raise DatasetError("ZIP con troppi file (max %d)" % ZIP_MAX_ENTRIES)
            for name in names:
                if not _is_audio(name):
                    continue
                data = archive.read(name)
                try:
                    duration, rate, channels = _probe_bytes(name, data)
                except DatasetError as exc:
                    errors.append(str(exc))
                    continue
                entries.append(
                    {
                        "name": _safe_name(name),
                        "duration_s": round(duration, 3),
                        "sample_rate": rate,
                        "channels": channels,
                    }
                )
    elif os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if not os.path.isfile(full) or not _is_audio(name):
                continue
            if len(entries) >= MAX_FILES:
                warnings.append("Limite di %d file raggiunto." % MAX_FILES)
                break
            try:
                duration, rate, channels = _probe_path(full)
            except DatasetError as exc:
                errors.append(str(exc))
                continue
            entries.append(
                {
                    "name": _safe_name(name),
                    "duration_s": round(duration, 3),
                    "sample_rate": rate,
                    "channels": channels,
                }
            )
    elif os.path.isfile(path) and _is_audio(path):
        duration, rate, channels = _probe_path(path)
        entries.append(
            {
                "name": _safe_name(path),
                "duration_s": round(duration, 3),
                "sample_rate": rate,
                "channels": channels,
            }
        )
    else:
        raise DatasetError("sorgente non supportata: serve una cartella o uno ZIP")

    accepted = [entry for entry in entries if entry["duration_s"] >= MIN_FILE_SECONDS]
    dropped = len(entries) - len(accepted)
    if dropped:
        warnings.append("%d file troppo corti ignorati (< %.0fs)." % (dropped, MIN_FILE_SECONDS))

    total = sum(entry["duration_s"] for entry in accepted)
    report: Dict[str, Any] = {
        "source": path,
        "files": len(accepted),
        "total_s": round(total, 2),
        "min_s": round(min((e["duration_s"] for e in accepted), default=0.0), 2),
        "max_s": round(max((e["duration_s"] for e in accepted), default=0.0), 2),
        "sample_rates": sorted({int(e["sample_rate"]) for e in accepted}),
        "channels": sorted({int(e["channels"]) for e in accepted}),
        "entries": accepted[:200],
        "warnings": warnings,
        "errors": errors,
    }
    if os.path.isdir(path) or os.path.isfile(path):
        try:
            from .curate import quick_quality

            quality = quick_quality(path, sample=20, seconds=15.0)
            report["quality"] = quality
            sampled = int(quality.get("files") or 0)
            if sampled:
                if int(quality.get("music_files") or 0) > 0:
                    warnings.append(
                        "%d/%d file sembrano contenere musica o jingle: usare "
                        "tools/curate_dataset.py per pulire il dataset."
                        % (int(quality["music_files"]), sampled)
                    )
                if int(quality.get("clipped_files") or 0) > 0:
                    warnings.append(
                        "%d/%d file saturano: abbassa il volume in ripresa o scarta quei file."
                        % (int(quality["clipped_files"]), sampled)
                    )
                if int(quality.get("noisy_files") or 0) > 0:
                    warnings.append(
                        "%d/%d file hanno molto rumore/spettro piatto: valuta la pulizia."
                        % (int(quality["noisy_files"]), sampled)
                    )
                if int(quality.get("stereo_files") or 0) > 0:
                    warnings.append(
                        "%d/%d file sono stereo: il training li converte in mono, "
                        "ma la voce deve essere centrata."
                        % (int(quality["stereo_files"]), sampled)
                    )
        except Exception:
            pass
    return _verdict(report)


def prepare_dataset(source: str, dest_raw: str) -> Dict[str, Any]:
    """Copia/estrae gli audio in ``dest_raw`` e restituisce il report del contenuto."""
    path = os.path.abspath(str(source or "").strip())
    if not os.path.exists(path):
        raise DatasetError("percorso dataset non trovato: %s" % path)
    os.makedirs(dest_raw, exist_ok=True)
    copied = 0
    total_bytes = 0
    seen: Dict[str, int] = {}

    def _target(name: str) -> str:
        safe = _safe_name(name)
        stem, ext = os.path.splitext(safe)
        count = seen.get(safe.lower(), 0)
        seen[safe.lower()] = count + 1
        if count:
            safe = "%s_%d%s" % (stem, count + 1, ext)
        return os.path.join(dest_raw, safe)

    if os.path.isfile(path) and path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith("/") or not _is_audio(name):
                    continue
                if copied >= MAX_FILES:
                    break
                data = archive.read(name)
                total_bytes += len(data)
                if total_bytes > MAX_TOTAL_BYTES:
                    raise DatasetError("ZIP troppo grande (max 2 GB di audio)")
                target = _target(name)
                with open(target, "wb") as handle:
                    handle.write(data)
                copied += 1
    elif os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if not os.path.isfile(full) or not _is_audio(name):
                continue
            if copied >= MAX_FILES:
                break
            size = os.path.getsize(full)
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise DatasetError("dataset troppo grande (max 2 GB)")
            shutil.copy2(full, _target(name))
            copied += 1
    else:
        shutil.copy2(path, _target(path))
        copied = 1

    report = inspect_source(dest_raw)
    report["copied"] = copied
    return report


def quick_check(source: str) -> Dict[str, Any]:
    """Controllo veloce (senza decodifica) usato all'avvio del job.

    L'analisi completa avviene nel worker dopo la copia: cosi' l'API risponde
    subito anche con ZIP grandi.
    """
    path = os.path.abspath(str(source or "").strip())
    if not os.path.exists(path):
        raise DatasetError("percorso dataset non trovato: %s" % path)
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = [n for n in archive.namelist() if not n.endswith("/")]
                audio = [n for n in names if _is_audio(n)]
                size = sum(info.file_size for info in archive.infolist() if not info.is_dir())
        except zipfile.BadZipFile as exc:
            raise DatasetError("ZIP non valido: %s" % exc)
        if not audio:
            raise DatasetError("lo ZIP non contiene file audio supportati")
        return {"kind": "zip", "audio_files": len(audio), "bytes": size}
    if os.path.isdir(path):
        audio = 0
        size = 0
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isfile(full) and _is_audio(name):
                audio += 1
                size += os.path.getsize(full)
        if not audio:
            raise DatasetError("la cartella non contiene file audio supportati")
        return {"kind": "dir", "audio_files": audio, "bytes": size}
    if os.path.isfile(path) and _is_audio(path):
        return {"kind": "file", "audio_files": 1, "bytes": os.path.getsize(path)}
    raise DatasetError("sorgente non supportata: serve una cartella, uno ZIP o un file audio")


def digest_manifest(report: Dict[str, Any]) -> str:
    """Impronta stabile del dataset (nome + durata) per riconoscere i duplicati."""
    payload = "\n".join(
        "%s:%.3f" % (entry["name"], entry["duration_s"])
        for entry in sorted(report.get("entries") or [], key=lambda item: item["name"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
