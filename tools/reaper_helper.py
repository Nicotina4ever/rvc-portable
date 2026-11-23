"""Helper CLI per REAPER (e per test manuali).

Converte uno o piu' file con il motore locale RVC Portable e stampa righe di
progresso leggibili da uno script ReaScript:

    PROGRESS <0-100> <stage>
    AUTO <json>            (solo con --auto)
    RESULT <json>          (riga finale)

Esempio:
    runtime\\python.exe -B tools\\reaper_helper.py --input voce.wav \
        --output-dir out --model Modelli\\voce.pth --index Modelli\\voce.index \
        --pitch 0 --method rmvpe --protect 0.33 --index-rate 0.3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.engine import InferParams  # noqa: E402
from app.core.engine_rvc import create_engine  # noqa: E402
from app.paths import AppPaths  # noqa: E402
from app.settings import SettingsManager  # noqa: E402


def emit(line: str) -> None:
    print(line, flush=True)


def progress(percent: float, stage: str = "") -> None:
    value = max(0.0, min(100.0, float(percent)))
    emit("PROGRESS %.1f %s" % (value, stage))


def unique_path(directory: str, stem: str, suffix: str = "") -> str:
    base = stem + suffix
    candidate = os.path.join(directory, base + ".wav")
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, "%s-%d.wav" % (base, counter))
        counter += 1
    return candidate


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RVC Portable helper per REAPER")
    parser.add_argument("--input", required=True, help="file audio di input")
    parser.add_argument("--output-dir", required=True, help="cartella di output")
    parser.add_argument("--model", required=True, help="modello .pth")
    parser.add_argument("--index", default="", help="indice .index (opzionale)")
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--method", default="rmvpe", choices=["rmvpe", "harvest", "crepe", "pm"])
    parser.add_argument("--protect", type=float, default=0.33)
    parser.add_argument("--index-rate", type=float, default=0.3)
    parser.add_argument("--formant", type=int, default=0, help="spostamento formanti (-12..12)")
    parser.add_argument("--filter-radius", type=int, default=3)
    parser.add_argument("--rms-mix-rate", type=float, default=0.25)
    parser.add_argument("--resample-sr", type=int, default=0)
    parser.add_argument("--version", default="v2", choices=["v1", "v2"])
    parser.add_argument("--device", default="auto")
    parser.add_argument("--suffix", default="_RVC")
    parser.add_argument("--auto", action="store_true", help="auto-test su campione di 10 s")
    parser.add_argument("--auto-seconds", type=float, default=10.0)
    parser.add_argument("--auto-methods", default="rmvpe,harvest")
    parser.add_argument("--completion-file", default="")
    parser.add_argument("--log-file", default="")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    source = os.path.abspath(args.input)
    if not os.path.isfile(source):
        emit("RESULT " + json.dumps({"ok": False, "error": "input non trovato: %s" % source}))
        return 2
    if not os.path.isfile(args.model):
        emit("RESULT " + json.dumps({"ok": False, "error": "modello non trovato: %s" % args.model}))
        return 2
    os.makedirs(args.output_dir, exist_ok=True)

    log_handle = None
    if args.log_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.log_file)), exist_ok=True)
        log_handle = open(args.log_file, "a", encoding="utf-8")

    def log(message: str) -> None:
        if log_handle:
            log_handle.write(str(message) + "\n")
            log_handle.flush()

    paths = AppPaths.create()
    manager = SettingsManager(paths)
    manager.load()
    manager.settings.audio.model_path = os.path.abspath(args.model)
    manager.settings.audio.index_path = os.path.abspath(args.index or "")
    engine = create_engine(paths, settings_manager=manager)

    base_params: Dict[str, Any] = {
        "pitch": int(args.pitch),
        "method": args.method,
        "protect": float(args.protect),
        "index_rate": float(args.index_rate),
        "formant": int(args.formant),
        "filter_radius": int(args.filter_radius),
        "rms_mix_rate": float(args.rms_mix_rate),
        "resample_sr": int(args.resample_sr),
        "model_version": args.version,
    }
    auto_report: Dict[str, Any] = {}
    try:
        progress(2.0, "loading")
        engine.load(
            os.path.abspath(args.model),
            os.path.abspath(args.index or ""),
            version=args.version,
            device=args.device,
        )
        progress(8.0, "loaded")

        if args.auto:
            from app.tuning.auto_tune import candidate_grid, run_auto_tune

            methods = [item.strip() for item in str(args.auto_methods).split(",") if item.strip()]
            grid = candidate_grid(methods=methods or ("rmvpe", "harvest"))

            def on_tune(done: int, total: int, candidate: Dict[str, Any]) -> None:
                progress(8.0 + 55.0 * (done / max(1, total)), "auto-test")
                log("auto %d/%d %s" % (done, total, json.dumps(candidate, ensure_ascii=False)))

            auto_report = run_auto_tune(
                engine,
                source,
                base_params,
                workdir=os.path.join(args.output_dir, "_autotest"),
                seconds=float(args.auto_seconds),
                candidates=grid,
                on_progress=on_tune,
            )
            best = auto_report.get("best") or {}
            if best:
                base_params.update(
                    {
                        "method": best.get("method", base_params["method"]),
                        "protect": float(best.get("protect", base_params["protect"])),
                        "index_rate": float(best.get("index_rate", base_params["index_rate"])),
                    }
                )
            emit("AUTO " + json.dumps({"best": best, "results": auto_report.get("results", [])}, ensure_ascii=False))
            log("auto best: %s" % json.dumps(best, ensure_ascii=False))

        params = InferParams(**base_params)
        stem, _ext = os.path.splitext(os.path.basename(source))
        target = unique_path(args.output_dir, stem, args.suffix)

        def on_stage(stage: str, percent) -> None:
            base = 65.0 if args.auto else 10.0
            span = 33.0 if args.auto else 88.0
            fraction = float(percent) if percent is not None else 0.0
            progress(base + span * max(0.0, min(1.0, fraction)), stage or "conversion")

        engine.infer(
            source,
            target,
            params,
            on_log=lambda message: log("[engine] %s" % message),
            on_stage=on_stage,
        )
        progress(100.0, "done")
        result = {
            "ok": True,
            "output": target,
            "input": source,
            "model": os.path.abspath(args.model),
            "index": os.path.abspath(args.index or ""),
            "params": params.to_dict(),
            "auto": {"best": auto_report.get("best", {})} if auto_report else {},
        }
        emit("RESULT " + json.dumps(result, ensure_ascii=False))
        if args.completion_file:
            with open(args.completion_file, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        return 0
    except Exception as exc:
        message = str(exc)
        log("ERRORE: %s" % message)
        result = {"ok": False, "error": message}
        emit("RESULT " + json.dumps(result, ensure_ascii=False))
        if args.completion_file:
            with open(args.completion_file, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        return 1
    finally:
        try:
            engine.shutdown()
        except Exception:
            pass
        if log_handle:
            log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
