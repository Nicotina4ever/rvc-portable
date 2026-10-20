"""Interfaccia a riga di comando (usata da launch.py e dagli strumenti)."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .paths import AppPaths
from .settings import SettingsManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rvc-portable",
        description="RVC Portable — NL Tools Suite (backend locale + interfaccia web)",
    )
    parser.add_argument("--version", action="store_true", help="mostra la versione ed esce")
    parser.add_argument("--doctor", action="store_true", help="esegue la diagnostica ed esce")
    parser.add_argument("--doctor-json", action="store_true", help="diagnostica in JSON")
    parser.add_argument("--data-dir", default=None, help="cartella dati (default: ./data)")
    parser.add_argument(
        "--config", "-c", default=None, help="percorso alternativo del file di configurazione"
    )
    parser.add_argument("--no-portable", action="store_true", help="usa la cartella dati utente")
    parser.add_argument("--host", default="127.0.0.1", help="indirizzo di ascolto (default loopback)")
    parser.add_argument("--port", type=int, default=0, help="porta (0 = casuale libera)")
    parser.add_argument("--allow-lan", action="store_true", help="consenti accesso da rete locale")
    parser.add_argument(
        "--browser",
        choices=("auto", "edge", "chrome", "default", "none"),
        default="auto",
        help="come aprire l'interfaccia",
    )
    parser.add_argument(
        "--app-mode",
        dest="app_mode",
        action="store_true",
        default=True,
        help="finestra app senza barre del browser (default)",
    )
    parser.add_argument(
        "--no-app-mode",
        dest="app_mode",
        action="store_false",
        help="apre una normale scheda del browser",
    )
    parser.add_argument("--headless", action="store_true", help="solo server, nessun browser")
    parser.add_argument("--console", action="store_true", help="log anche su console")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="livello di log",
    )
    parser.add_argument(
        "--idle-exit-minutes",
        type=int,
        default=15,
        help="spegni il server senza client connessi (0 = disabilitato)",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print("RVC Portable %s" % __version__)
        return 0

    paths = AppPaths.create(
        data_dir=args.data_dir,
        prefer_portable=not args.no_portable,
        config_path=args.config,
    )
    manager = SettingsManager(paths)
    try:
        manager.load()
    except Exception:  # la diagnostica riporta il problema
        pass

    if args.doctor or args.doctor_json:
        from . import doctor

        report = doctor.run_checks(paths, manager.settings, force_probe=True)
        if args.doctor_json:
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        else:
            print(doctor.summary_text(report))
            for warning in manager.warnings:
                print("warning: %s" % warning)
        return 0 if report.get("overall") != "fail" else 1

    from .launcher import run

    return run(paths, args)


if __name__ == "__main__":
    sys.exit(main())
