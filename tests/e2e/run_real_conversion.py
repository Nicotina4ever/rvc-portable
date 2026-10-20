"""Conversione reale end-to-end con il motore RVC (worker persistente).

Uso (dalla radice del progetto, con il runtime del motore):

    runtime\\python.exe -B tests\\e2e\\run_real_conversion.py
    runtime\\python.exe -B tests\\e2e\\run_real_conversion.py --device cpu --seconds 3

Lo script:

1. prepara un campione audio in ``data/cache`` (usa ``gate0-sample.wav`` se
   presente, altrimenti ne genera uno sintetico con la sola stdlib);
2. carica ``Modelli/Nicola-Spot2.pth`` + indice ``added_IVF1456...`` su
   ``cuda:0`` (o il device richiesto) tramite ``RvcEngine``;
3. converte il campione e verifica: output esistente, non silenzioso,
   sample rate > 0, durata > 0;
4. stampa il fattore tempo reale (RTF = tempo di inferenza / durata audio);
5. verifica che i file in ``Modelli/`` **non siano stati modificati**.

Exit code 0 = tutto ok, 1 = fallimento con messaggio azionabile.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import traceback
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.audio import probe_audio  # noqa: E402
from app.core.engine import InferParams, pcm_peak_amplitude  # noqa: E402
from app.core.engine_rvc import RvcEngine  # noqa: E402
from app.paths import AppPaths  # noqa: E402
from app.settings import SettingsManager  # noqa: E402

DEFAULT_MODEL = os.path.join("Modelli", "Nicola-Spot2.pth")
DEFAULT_INDEX = os.path.join(
    "Modelli", "added_IVF1456_Flat_nprobe_1_Nicola-Spot2_v2.index"
)
SAMPLE_PATH = os.path.join("data", "cache", "gate0-sample.wav")
OUTPUT_PATH = os.path.join("data", "cache", "gate0-engine-out.wav")
MIN_OUTPUT_PEAK = 0.005


def log(message: str) -> None:
    print("[e2e] %s" % message, flush=True)


def generate_sample(path: str, seconds: float = 6.0, sample_rate: int = 44100) -> str:
    """Voce sintetica intelligibile per una conversione RVC (solo stdlib)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    total = int(seconds * sample_rate)
    frames = bytearray()
    for index in range(total):
        t = index / float(sample_rate)
        f0 = 120.0 + 18.0 * math.sin(2.0 * math.pi * 0.7 * t)
        phase = 2.0 * math.pi * f0 * t
        value = (
            0.55 * math.sin(phase)
            + 0.25 * math.sin(2.0 * phase)
            + 0.12 * math.sin(3.0 * phase)
            + 0.05 * math.sin(5.0 * phase)
        )
        # inviluppo a sillabe, con pause (piu' simile a parlato)
        syllable = 0.5 + 0.5 * math.sin(2.0 * math.pi * 2.2 * t - math.pi / 2.0)
        envelope = max(0.0, syllable) ** 1.5
        sample = int(max(-1.0, min(1.0, value * envelope)) * 16000)
        frames += int(sample).to_bytes(2, "little", signed=True)
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    os.replace(tmp, path)
    return path


def ensure_sample(seconds: float) -> str:
    path = os.path.join(ROOT, SAMPLE_PATH)
    if os.path.isfile(path):
        try:
            info = probe_audio(path)
            if info.get("duration_s", 0) > 0.5:
                log("campione esistente: %s (%.2fs)" % (path, info["duration_s"]))
                return path
        except Exception as exc:  # pragma: no cover - campione corrotto
            log("campione esistente non valido (%s): lo rigenero" % exc)
    log("genero campione sintetico (%.1fs)..." % seconds)
    return generate_sample(path, seconds=seconds)


def snapshot_tree(directory: str):
    snapshot = {}
    for current, _dirnames, filenames in os.walk(directory):
        for name in filenames:
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            snapshot[os.path.normcase(path)] = (
                int(stat.st_size),
                int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
            )
    return snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="E2E reale del motore RVC")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--method", default="rmvpe")
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    args = parser.parse_args(argv)

    started = time.time()
    paths = AppPaths.create()
    manager = SettingsManager(paths)
    manager.load()
    device = str(args.device or manager.settings.engine.device or "auto")

    model_path = args.model if os.path.isabs(args.model) else os.path.join(ROOT, args.model)
    index_path = args.index if os.path.isabs(args.index) else os.path.join(ROOT, args.index)
    if not os.path.isfile(model_path):
        log("ERRORE: modello non trovato: %s" % model_path)
        return 1
    if not os.path.isfile(index_path):
        log("ERRORE: indice non trovato: %s" % index_path)
        return 1

    try:
        sample = ensure_sample(args.seconds)
    except Exception:
        log("ERRORE: impossibile preparare il campione:\n%s" % traceback.format_exc())
        return 1

    models_dir = os.path.join(ROOT, "Modelli")
    before = snapshot_tree(models_dir)
    output_path = os.path.join(ROOT, OUTPUT_PATH)
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    engine = RvcEngine(paths, manager)
    logs = []
    stages = []

    def on_log(message: str) -> None:
        logs.append(str(message))
        log("log: %s" % message)

    def on_stage(name: str, progress) -> None:
        stages.append(name)
        log("stage: %s (%s)" % (name, progress))

    exit_code = 0
    try:
        status = engine.status()
        if not status.available:
            log("ERRORE: motore non disponibile: %s" % status.message)
            return 1
        log("runtime motore: %s" % status.extra.get("engine_python", "?"))

        log("carico il modello %s" % os.path.basename(model_path))
        load_started = time.time()
        engine.load(model_path, index_path, version="v2", device=device)
        load_elapsed = time.time() - load_started
        loaded_status = engine.status()
        log(
            "modello caricato in %.2fs (device=%s, busy=%s)"
            % (load_elapsed, loaded_status.device, loaded_status.busy)
        )

        params = InferParams(
            pitch=int(args.pitch),
            method=str(args.method),
            protect=0.33,
            index_rate=0.3,
            filter_radius=3,
            rms_mix_rate=0.25,
            resample_sr=0,
            model_version="v2",
            output_format="wav",
        )
        log("avvio inferenza (%s)..." % params.method)
        result = engine.infer(
            sample, output_path, params, on_log=on_log, on_stage=on_stage
        )
        if not result.ok:
            log(
                "ERRORE inferenza: %s: %s\n%s"
                % (result.error_code, result.error_message, result.detail)
            )
            return 1
        if not os.path.isfile(output_path):
            log("ERRORE: output non scritto: %s" % output_path)
            return 1

        info = probe_audio(output_path)
        peak = pcm_peak_amplitude(output_path)
        duration_s = float(info.get("duration_s") or 0.0)
        sample_rate = int(info.get("sample_rate") or 0)
        elapsed = float(result.elapsed_s or 0.0)
        rtf = (elapsed / duration_s) if duration_s > 0 else float("inf")
        log(
            "OUTPUT: %s | %.2f s @ %d Hz | picco %.4f | inferenza %.2fs | RTF %.2f | "
            "load %.2fs | totale %.2fs"
            % (
                output_path,
                duration_s,
                sample_rate,
                peak,
                elapsed,
                rtf,
                load_elapsed,
                time.time() - started,
            )
        )
        log(
            "stage ricevuti: %s"
            % ", ".join(dict.fromkeys(stages)) if stages else "stage ricevuti: nessuno"
        )

        failures = []
        if sample_rate <= 0:
            failures.append("sample rate non valido (%s)" % sample_rate)
        if duration_s <= 0.05:
            failures.append("durata non valida (%.3fs)" % duration_s)
        if peak < MIN_OUTPUT_PEAK:
            failures.append("output silenzioso/quasi silenzioso (picco %.4f)" % peak)
        if result.duration_s <= 0:
            failures.append("durata riportata dal motore non valida")
        if not stages:
            failures.append("nessuno stage ricevuto dal motore")

        after = snapshot_tree(models_dir)
        if before != after:
            changed = sorted(
                set(before) ^ set(after)
                | {key for key in set(before) & set(after) if before[key] != after[key]}
            )
            failures.append("file in Modelli/ modificati: %s" % ", ".join(changed[:5]))

        if failures:
            for failure in failures:
                log("ERRORE: %s" % failure)
            exit_code = 1
        else:
            log("E2E OK: conversione reale riuscita, Modelli/ invariata")
    except Exception:
        log("ERRORE inatteso:\n%s" % traceback.format_exc())
        exit_code = 1
    finally:
        try:
            engine.shutdown()
        except Exception:
            log("warning: shutdown del motore fallito:\n%s" % traceback.format_exc())
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
