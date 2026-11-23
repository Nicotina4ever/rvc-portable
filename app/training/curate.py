"""Cura e pulizia del dataset di addestramento.

Analizza ogni file audio, calcola metriche di qualità (durata, loudness, silenzio,
clipping, rumore, probabilità di musica), trova duplicati e produce:

- ``report.json`` / ``report.csv`` / ``report.md`` con la classifica;
- ``clean/`` con i file promossi (copia o riscrittura normalizzata);
- ``validation/`` con un sottoinsieme tenuto fuori dal training per i test.

Le euristiche non sostituiscono l'ascolto: servono a togliere musica, jingle,
file rotti e duplicati prima di addestrare un modello professionale.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import re
import shutil
from typing import Any, Callable, Dict, List, Optional

AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".flac",
    ".wma",
    ".aiff",
    ".aif",
}

TARGET_SR = 48000
SILENCE_DB = -45.0
CLIP_LEVEL = 0.995


def _iter_audio(source: str) -> List[str]:
    if os.path.isfile(source):
        return [source] if os.path.splitext(source)[1].lower() in AUDIO_EXTENSIONS else []
    files: List[str] = []
    for base, dirs, names in os.walk(source):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in names:
            if os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS:
                files.append(os.path.join(base, name))
    files.sort(key=lambda item: item.lower())
    return files


def _load_mono(path: str) -> tuple:
    import numpy as np
    import soundfile as sf

    try:
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        channels = int(data.shape[1])
        mono = data.mean(axis=1) if channels > 1 else data[:, 0]
        return np.asarray(mono, dtype=np.float32), int(rate), channels, data
    except Exception:
        import librosa

        mono, rate = librosa.load(path, sr=None, mono=True)
        return np.asarray(mono, dtype=np.float32), int(rate), 1, None


def _db(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-9))


def analyze_file(path: str, sample_seconds: float = 30.0) -> Dict[str, Any]:
    """Metriche oggettive di un file; nessuna modifica al file."""
    import numpy as np

    result: Dict[str, Any] = {
        "path": os.path.abspath(path),
        "name": os.path.basename(path),
        "duration_s": 0.0,
        "sample_rate": 0,
        "channels": 0,
        "peak_dbfs": -120.0,
        "rms_dbfs": -120.0,
        "clipping": 0.0,
        "silence_ratio": 1.0,
        "flatness": 0.0,
        "percussive_ratio": 0.0,
        "zcr": 0.0,
        "beat_strength": 0.0,
        "music_likelihood": 0.0,
        "dual_mono": False,
        "decode_error": "",
    }
    try:
        mono, rate, channels, data = _load_mono(path)
    except Exception as exc:
        result["decode_error"] = str(exc)[:300]
        return result

    duration = len(mono) / float(rate) if rate else 0.0
    result.update(
        duration_s=round(duration, 2),
        sample_rate=rate,
        channels=channels,
    )
    if len(mono) == 0:
        result["decode_error"] = "audio vuoto"
        return result

    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(np.square(mono))))
    result["peak_dbfs"] = round(_db(peak), 1)
    result["rms_dbfs"] = round(_db(rms), 1)
    result["clipping"] = round(float(np.mean(np.abs(mono) >= CLIP_LEVEL)), 4)
    silent = np.abs(mono) < (10.0 ** (SILENCE_DB / 20.0))
    result["silence_ratio"] = round(float(np.mean(silent)), 3)

    if channels > 1 and data is not None:
        left = data[:, 0]
        right = data[:, 1]
        denom = float(np.std(left) * np.std(right)) + 1e-9
        correlation = float(np.mean((left - left.mean()) * (right - right.mean())) / denom)
        result["dual_mono"] = bool(correlation > 0.999)

    sample = mono[: int(min(len(mono), sample_seconds * rate))]
    if len(sample) < 1024:
        return result
    try:
        import librosa

        flatness = librosa.feature.spectral_flatness(y=sample)[0]
        zcr = librosa.feature.zero_crossing_rate(sample)[0]
        result["flatness"] = round(float(np.median(flatness)), 4)
        result["zcr"] = round(float(np.median(zcr)), 4)
        harmonic, percussive = librosa.effects.hpss(sample)
        energy_h = float(np.sum(np.square(harmonic)))
        energy_p = float(np.sum(np.square(percussive)))
        ratio = energy_p / (energy_h + energy_p + 1e-9)
        result["percussive_ratio"] = round(float(ratio), 3)

        # Periodicità del ritmo: la musica con groove ha un picco netto
        # nell'autocorrelazione dell'onset envelope; la voce no.
        onset = librosa.onset.onset_strength(y=sample, sr=rate)
        if onset.size >= 16:
            auto = librosa.autocorrelate(onset - onset.mean())
            auto = auto / (auto[0] + 1e-9)
            fps = float(rate) / 512.0
            low = int(fps * 60.0 / 200.0)
            high = int(fps * 60.0 / 60.0)
            if high > low + 1:
                result["beat_strength"] = round(float(np.max(auto[low:high])), 3)
    except Exception as exc:  # metriche spettrali opzionali
        result["decode_error"] = (result["decode_error"] + " " + str(exc)).strip()[:300]

    # Euristica prudente: la sola energia percussiva non basta (anche la voce
    # ha consonanti), quindi pesa soprattutto la periodicità ritmica.
    perc = float(result["percussive_ratio"])
    beat = float(result["beat_strength"])
    music = beat * 1.9 + max(0.0, perc - 0.58) * 1.1
    if result["silence_ratio"] > 0.5:
        music *= 0.7
    result["music_likelihood"] = round(float(min(1.0, max(0.0, music))), 3)
    return result


def _quality(metrics: Dict[str, Any]) -> float:
    """Punteggio 0-100 (più alto = più adatto al training)."""
    if metrics.get("decode_error"):
        return 0.0
    score = 100.0
    duration = float(metrics.get("duration_s") or 0.0)
    if duration < 3.0:
        score -= 80
    elif duration < 6.0:
        score -= 20
    rms = float(metrics.get("rms_dbfs") or -120.0)
    if rms < -36.0:
        score -= min(50.0, (-36.0 - rms) * 3.0)
    elif rms > -10.0:
        score -= min(30.0, (rms + 10.0) * 2.0)
    score -= float(metrics.get("silence_ratio") or 0.0) * 35.0
    score -= float(metrics.get("clipping") or 0.0) * 300.0
    score -= float(metrics.get("music_likelihood") or 0.0) * 30.0
    flatness = float(metrics.get("flatness") or 0.0)
    if flatness > 0.30:
        score -= min(25.0, (flatness - 0.30) * 80.0)
    if float(metrics.get("peak_dbfs") or -120.0) < -12.0:
        score -= 5.0
    return round(max(0.0, min(100.0, score)), 1)


def _classify(metrics: Dict[str, Any], options: Dict[str, Any]) -> tuple:
    reasons: List[str] = []
    if metrics.get("decode_error"):
        return "reject", ["file non decodificabile"]
    duration = float(metrics.get("duration_s") or 0.0)
    if duration < float(options.get("min_duration", 3.0)):
        reasons.append("troppo corto (%.1fs)" % duration)
    if duration > float(options.get("max_duration", 120.0)):
        reasons.append("molto lungo (%.1fs)" % duration)
    if float(metrics.get("clipping") or 0.0) > float(options.get("max_clipping", 0.01)):
        reasons.append("clipping elevato")
    if float(metrics.get("rms_dbfs") or -120.0) < float(options.get("min_rms", -40.0)):
        reasons.append("segnale troppo basso")
    if float(metrics.get("silence_ratio") or 0.0) > float(options.get("max_silence", 0.65)):
        reasons.append("troppo silenzio")
    music = float(metrics.get("music_likelihood") or 0.0)
    if music > float(options.get("max_music", 0.6)):
        reasons.append("musica/jingle probabile (ascolta e valuta)")
    if reasons:
        hard = (
            duration < float(options.get("min_duration", 3.0))
            or metrics.get("decode_error")
            or float(metrics.get("clipping") or 0.0) > float(options.get("max_clipping", 0.01))
            or float(metrics.get("rms_dbfs") or -120.0) < float(options.get("min_rms", -40.0))
        )
        return ("reject" if hard else "review"), reasons
    return "keep", []


def _fingerprint(path: str, metrics: Dict[str, Any]) -> List[float]:
    """MFCC media+deviazione standard: più selettivo del chroma per la voce."""
    import numpy as np

    try:
        import librosa

        mono, rate, _channels, _data = _load_mono(path)
        sample = mono[: min(len(mono), 20 * rate)]
        mfcc = librosa.feature.mfcc(y=sample, sr=rate, n_mfcc=20)
        mean = np.mean(mfcc, axis=1)
        std = np.std(mfcc, axis=1)
        return [float(item) for item in np.concatenate([mean, std])]
    except Exception:
        return []


def _is_duplicate(first: List[float], second: List[float], threshold: float = 0.985) -> bool:
    if not first or not second:
        return False
    dot = sum(a * b for a, b in zip(first, second))
    norm_a = math.sqrt(sum(a * a for a in first))
    norm_b = math.sqrt(sum(b * b for b in second))
    if norm_a <= 0 or norm_b <= 0:
        return False
    return (dot / (norm_a * norm_b)) >= threshold


def _rewrite(source: str, target: str, options: Dict[str, Any]) -> bool:
    """Decodifica, taglia silenzi, converte in mono/48k e scrive WAV."""
    import numpy as np
    import soundfile as sf

    try:
        mono, rate, _channels, _data = _load_mono(source)
        if float(options.get("trim_silence", 0) or 0) > 0:
            import librosa

            mono, _index = librosa.effects.trim(
                mono, top_db=float(options.get("trim_db", 35.0))
            )
        target_rate = int(options.get("resample_sr", TARGET_SR) or TARGET_SR)
        if rate != target_rate:
            import librosa

            mono = librosa.resample(mono, orig_sr=rate, target_sr=target_rate)
            rate = target_rate
        peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
        if peak > 0.999:
            mono = mono * (0.999 / peak)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        sf.write(target, np.asarray(mono, dtype=np.float32), rate, subtype="PCM_16")
        return True
    except Exception:
        return False


def curate(
    source: str,
    output_dir: str,
    options: Optional[Dict[str, Any]] = None,
    on_progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Analizza il dataset, produce report e cartelle clean/validation."""
    options = dict(options or {})
    options.setdefault("min_duration", 3.0)
    options.setdefault("max_duration", 120.0)
    options.setdefault("max_clipping", 0.01)
    options.setdefault("min_rms", -40.0)
    options.setdefault("max_silence", 0.65)
    options.setdefault("max_music", 0.45)
    options.setdefault("resample_sr", TARGET_SR)
    options.setdefault("trim_silence", True)
    options.setdefault("validation", 0)
    options.setdefault("dedupe", True)
    options.setdefault("near_dupes", False)
    options.setdefault("rewrite", False)

    files = _iter_audio(source)
    if not files:
        raise ValueError("nessun file audio trovato in %s" % source)

    metrics_list: List[Dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        metrics = analyze_file(path)
        metrics["quality"] = _quality(metrics)
        verdict, reasons = _classify(metrics, options)
        metrics["verdict"] = verdict
        metrics["reasons"] = reasons
        metrics_list.append(metrics)
        if on_progress:
            on_progress(index, len(files), metrics)

    duplicates: List[Dict[str, Any]] = []
    if options.get("dedupe"):
        exact: Dict[str, str] = {}
        for metrics in metrics_list:
            try:
                digest = hashlib.sha256()
                with open(metrics["path"], "rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                key = digest.hexdigest()
            except OSError:
                key = ""
            if key and key in exact:
                metrics["verdict"] = "reject"
                metrics["reasons"] = ["duplicato esatto di %s" % os.path.basename(exact[key])]
                duplicates.append({"path": metrics["path"], "duplicate_of": exact[key]})
            elif key:
                exact[key] = metrics["path"]
        # La similarità va attivata esplicitamente: sulla voce due spot diversi
        # possono somigliarsi molto e verrebbero scartati per errore.
        if options.get("near_dupes"):
            fingerprints = {}
            for metrics in metrics_list:
                if metrics["verdict"] != "keep":
                    continue
                fingerprint = _fingerprint(metrics["path"], metrics)
                for other_path, other in fingerprints.items():
                    if abs(float(other.get("duration_s") or 0) - float(metrics.get("duration_s") or 0)) > 0.5:
                        continue
                    if _is_duplicate(fingerprint, other["fingerprint"], threshold=0.995):
                        metrics["verdict"] = "reject"
                        metrics["reasons"] = ["simile a %s" % os.path.basename(other_path)]
                        duplicates.append({"path": metrics["path"], "duplicate_of": other_path})
                        break
                else:
                    fingerprints[metrics["path"]] = {
                        "fingerprint": fingerprint,
                        "duration_s": metrics.get("duration_s"),
                    }

    keep = [item for item in metrics_list if item["verdict"] == "keep"]
    review = [item for item in metrics_list if item["verdict"] == "review"]
    reject = [item for item in metrics_list if item["verdict"] == "reject"]

    os.makedirs(output_dir, exist_ok=True)
    clean_dir = os.path.join(output_dir, "clean")
    review_dir = os.path.join(output_dir, "review")
    validation_dir = os.path.join(output_dir, "validation")
    for directory in (clean_dir, review_dir, validation_dir):
        os.makedirs(directory, exist_ok=True)

    def _target(directory: str, path: str, used: set, force_wav: bool = False) -> str:
        base = re.sub(r"[^A-Za-z0-9._\- ]+", "_", os.path.basename(path)).strip(" ._")
        if not base:
            base = "audio.wav"
        stem, ext = os.path.splitext(base)
        if force_wav:
            ext = ".wav"
        candidate = stem + ext
        counter = 2
        while candidate.lower() in used:
            candidate = "%s_%d%s" % (stem, counter, ext)
            counter += 1
        used.add(candidate.lower())
        return os.path.join(directory, candidate)

    validation_count = int(options.get("validation") or 0)
    validation_paths: List[str] = []
    if validation_count > 0 and keep:
        random.seed(12345)
        validation_count = min(validation_count, max(1, len(keep) // 5))
        validation_paths = [item["path"] for item in random.sample(keep, validation_count)]

    used_clean: set = set()
    used_review: set = set()
    exported_clean = 0
    exported_validation = 0
    for metrics in keep:
        is_validation = metrics["path"] in validation_paths
        directory = validation_dir if is_validation else clean_dir
        used = used_clean if not is_validation else None
        target = _target(
            directory,
            metrics["path"],
            used if used is not None else set(),
            force_wav=bool(options.get("rewrite")),
        )
        if options.get("rewrite"):
            ok = _rewrite(metrics["path"], target, options)
        else:
            try:
                shutil.copy2(metrics["path"], target)
                ok = True
            except OSError:
                ok = False
        metrics["exported"] = target if ok else ""
        metrics["split"] = "validation" if is_validation else "train"
        if ok:
            if is_validation:
                exported_validation += 1
            else:
                exported_clean += 1
    for metrics in review:
        target = _target(review_dir, metrics["path"], used_review)
        try:
            shutil.copy2(metrics["path"], target)
            metrics["exported"] = target
            metrics["split"] = "review"
        except OSError:
            metrics["exported"] = ""
    for metrics in reject:
        metrics["exported"] = ""
        metrics["split"] = "reject"

    summary = {
        "source": os.path.abspath(source),
        "output": os.path.abspath(output_dir),
        "files": len(metrics_list),
        "keep": len(keep),
        "review": len(review),
        "reject": len(reject),
        "exported_clean": exported_clean,
        "exported_validation": exported_validation,
        "duplicates": duplicates,
        "total_duration_s": round(sum(float(item.get("duration_s") or 0) for item in keep), 2),
        "average_quality": round(
            sum(float(item.get("quality") or 0) for item in keep) / max(1, len(keep)), 1
        ),
        "options": options,
        "files_detail": metrics_list,
    }
    _write_reports(output_dir, summary)
    return summary


def _write_reports(output_dir: str, summary: Dict[str, Any]) -> None:
    with open(os.path.join(output_dir, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    columns = [
        "name",
        "path",
        "verdict",
        "quality",
        "duration_s",
        "sample_rate",
        "channels",
        "rms_dbfs",
        "peak_dbfs",
        "clipping",
        "silence_ratio",
        "flatness",
        "beat_strength",
        "music_likelihood",
        "split",
        "reasons",
        "exported",
    ]
    with open(os.path.join(output_dir, "report.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in summary["files_detail"]:
            row = dict(item)
            row["reasons"] = "; ".join(item.get("reasons") or [])
            writer.writerow(row)

    lines = [
        "# Report cura dataset",
        "",
        "- Sorgente: `%s`" % summary["source"],
        "- File analizzati: **%d**" % summary["files"],
        "- Promossi (training): **%d**" % summary["keep"],
        "- Da rivedere: **%d**" % summary["review"],
        "- Scartati: **%d**" % summary["reject"],
        "- Durata totale promossa: **%.1f min**" % (summary["total_duration_s"] / 60.0),
        "- Qualità media: **%.1f/100**" % summary["average_quality"],
        "",
        "## File promossi",
        "",
        "| File | Durata | Qualità | Musica |",
        "|---|---:|---:|---:|",
    ]
    for item in summary["files_detail"]:
        if item.get("verdict") != "keep":
            continue
        lines.append(
            "| %s | %.1fs | %.1f | %.2f |"
            % (item.get("name"), float(item.get("duration_s") or 0), float(item.get("quality") or 0), float(item.get("music_likelihood") or 0))
        )
    lines.append("")
    lines.append("## Da rivedere / scartati")
    lines.append("")
    for item in summary["files_detail"]:
        if item.get("verdict") == "keep":
            continue
        lines.append(
            "- **%s** — %s: %s"
            % (item.get("name"), item.get("verdict"), "; ".join(item.get("reasons") or []))
        )
    with open(os.path.join(output_dir, "report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def quick_quality(source: str, sample: int = 20, seconds: float = 20.0) -> Dict[str, Any]:
    """Analisi veloce su un campione di file (per la UI di addestramento)."""
    files = _iter_audio(source)
    if not files:
        return {"files": 0}
    step = max(1, len(files) // max(1, sample))
    selected = files[::step][:sample]
    metrics = [analyze_file(path, sample_seconds=seconds) for path in selected]
    ok = [item for item in metrics if not item.get("decode_error")]
    if not ok:
        return {"files": 0}
    return {
        "files": len(selected),
        "duration_s": round(sum(float(item.get("duration_s") or 0) for item in ok), 1),
        "rms_dbfs": round(sum(float(item.get("rms_dbfs") or -120.0) for item in ok) / len(ok), 1),
        "clipping": round(sum(float(item.get("clipping") or 0) for item in ok) / len(ok), 4),
        "silence_ratio": round(sum(float(item.get("silence_ratio") or 0) for item in ok) / len(ok), 3),
        "music_likelihood": round(sum(float(item.get("music_likelihood") or 0) for item in ok) / len(ok), 3),
        "noisy_files": sum(1 for item in ok if float(item.get("flatness") or 0) > 0.3),
        "music_files": sum(1 for item in ok if float(item.get("music_likelihood") or 0) > 0.5),
        "clipped_files": sum(1 for item in ok if float(item.get("clipping") or 0) > 0.01),
        "stereo_files": sum(1 for item in ok if int(item.get("channels") or 0) > 1),
        "sample_rates": sorted({int(item.get("sample_rate") or 0) for item in ok}),
    }
