"""Cura il dataset di addestramento: analisi, deduplica, report e cartelle clean/.

Esempi:
    runtime\\python.exe -B tools\\curate_dataset.py --source "Modelli\\Dataset_Spot_Locali" ^
        --out "Modelli\\Dataset_Spot_Locali_pulito" --validation 5

    # solo analisi, nessuna copia
    runtime\\python.exe -B tools\\curate_dataset.py --source dataset --out report --dry-run

    # riscrive in WAV 48k mono, taglia i silenzi, tiene 3 file per la validazione
    runtime\\python.exe -B tools\\curate_dataset.py --source dataset --out curato ^
        --rewrite --trim-silence --resample 48000 --validation 3

I file originali non vengono mai modificati.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.training.curate import curate  # noqa: E402


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Pulisce e organizza un dataset RVC")
    parser.add_argument("--source", required=True, help="cartella (o file) del dataset")
    parser.add_argument("--out", required=True, help="cartella di output (report + clean/)")
    parser.add_argument("--dry-run", action="store_true", help="solo report, nessuna copia")
    parser.add_argument("--rewrite", action="store_true", help="riscrive WAV 48k mono puliti")
    parser.add_argument("--trim-silence", action="store_true", help="taglia silenzi iniziali/finali")
    parser.add_argument("--resample", type=int, default=48000, help="sample rate di output")
    parser.add_argument("--min-duration", type=float, default=3.0)
    parser.add_argument("--max-duration", type=float, default=120.0)
    parser.add_argument("--max-music", type=float, default=0.45, help="soglia musica (0-1)")
    parser.add_argument("--max-silence", type=float, default=0.65)
    parser.add_argument("--min-rms", type=float, default=-40.0)
    parser.add_argument("--max-clipping", type=float, default=0.01)
    parser.add_argument("--validation", type=int, default=0, help="file tenuti fuori dal training")
    parser.add_argument("--no-dedupe", action="store_true", help="disattiva il controllo duplicati")
    parser.add_argument("--near-dupes", action="store_true", help="scarta anche file molto simili (rischioso sulla voce)")
    parser.add_argument("--limit", type=int, default=0, help="analizza solo i primi N file (test)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    options = {
        "min_duration": args.min_duration,
        "max_duration": args.max_duration,
        "max_music": args.max_music,
        "max_silence": args.max_silence,
        "min_rms": args.min_rms,
        "max_clipping": args.max_clipping,
        "validation": args.validation,
        "dedupe": not args.no_dedupe,
        "near_dupes": bool(args.near_dupes),
        "rewrite": bool(args.rewrite and not args.dry_run),
        "trim_silence": bool(args.trim_silence),
        "resample_sr": int(args.resample),
    }
    if args.limit:
        # limite solo per prove: taglio la lista prima di analizzare
        from app.training import curate as curate_module

        original = curate_module._iter_audio

        def limited(source):
            return original(source)[: args.limit]

        curate_module._iter_audio = limited  # type: ignore[assignment]

    def on_progress(done: int, total: int, item: dict) -> None:
        name = os.path.basename(item.get("path") or "")
        print(
            "PROGRESS %d %d %s | %s %.1fs q=%.0f"
            % (
                done,
                total,
                item.get("verdict", "?"),
                name,
                float(item.get("duration_s") or 0),
                float(item.get("quality") or 0),
            ),
            flush=True,
        )

    try:
        summary = curate(args.source, args.out, options, on_progress=on_progress)
    except (OSError, ValueError) as exc:
        print("ERRORE: %s" % exc, file=sys.stderr)
        return 2

    print(
        "\nFile: %d · promossi %d (%.1f min) · da rivedere %d · scartati %d"
        % (
            summary["files"],
            summary["keep"],
            summary["total_duration_s"] / 60.0,
            summary["review"],
            summary["reject"],
        )
    )
    print("Qualita media promossi: %.1f/100" % summary["average_quality"])
    if summary["duplicates"]:
        print("Duplicati/simili: %d" % len(summary["duplicates"]))
    print("Report: %s" % os.path.join(summary["output"], "report.md"))
    if args.dry_run:
        print("Dry-run: nessun file copiato.")
    else:
        print("Cartelle: %s , %s , %s" % (
            os.path.join(summary["output"], "clean"),
            os.path.join(summary["output"], "review"),
            os.path.join(summary["output"], "validation"),
        ))
    print(json.dumps({key: summary[key] for key in ("keep", "review", "reject", "exported_clean", "exported_validation")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
