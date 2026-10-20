"""Setup e verifica dell'ambiente multi-OS.

Windows: verifica/ripristina il runtime portatile (Python 3.9.13 con il motore).
macOS/Linux: crea ``runtime/`` come virtualenv Python 3.10 con i pin verificati.

Uso:
    python tools/bootstrap.py --check
    python tools/bootstrap.py --install
    python tools/bootstrap.py --install --profile cpu
    python tools/bootstrap.py --restore "Progetto/RVC-PortableConMonitoraggio.zip"
    python tools/bootstrap.py --dev
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = os.name == "nt"
RUNTIME_DIR = os.path.join(ROOT, "runtime")
DEV_TARGET = os.path.join(ROOT, ".dev", "site-packages")
DEV_PTH = (
    os.path.join(RUNTIME_DIR, "Lib", "site-packages", "zz_dev_site_packages.pth")
    if IS_WINDOWS
    else None
)

PROBE = r"""
import json, sys, os, importlib.util
out = {"python": sys.version.split()[0], "executable": sys.executable}
def spec(name):
    try:
        return importlib.util.find_spec(name)
    except Exception:
        return None
out["rvc_python"] = spec("rvc_python") is not None
out["fairseq"] = spec("fairseq") is not None
out["fastapi"] = spec("fastapi") is not None
out["requests"] = spec("requests") is not None
out["soundfile"] = spec("soundfile") is not None
out["av"] = spec("av") is not None
try:
    import torch
    out["torch"] = torch.__version__
    out["cuda"] = bool(torch.cuda.is_available())
    out["gpu"] = torch.cuda.get_device_name(0) if out["cuda"] else ""
except Exception as exc:
    out["torch"] = ""
    out["cuda"] = False
    out["torch_error"] = repr(exc)
try:
    spec = importlib.util.find_spec("rvc_python")
    if spec and spec.submodule_search_locations:
        base = os.path.join(list(spec.submodule_search_locations)[0], "base_model")
        out["base_models"] = {
            name: os.path.getsize(os.path.join(base, name))
            for name in ("hubert_base.pt", "rmvpe.pt")
            if os.path.isfile(os.path.join(base, name))
        }
except Exception:
    out["base_models"] = {}
print(json.dumps(out))
"""


def _runtime_python() -> Optional[str]:
    candidates = (
        [os.path.join(RUNTIME_DIR, "python.exe")]
        if IS_WINDOWS
        else [os.path.join(RUNTIME_DIR, "bin", "python3")]
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _run(cmd: List[str], env=None, check: bool = True) -> int:
    print("$ " + " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, env=env)
    if check and completed.returncode != 0:
        raise SystemExit("comando fallito con codice %d" % completed.returncode)
    return completed.returncode


def detect_system() -> dict:
    info = {
        "os": sys.platform,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "runtime_python": _runtime_python(),
    }
    return info


def verify(python: str) -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [python, "-B", "-c", PROBE], capture_output=True, text=True, env=env, cwd=ROOT
    )
    if completed.returncode != 0:
        return {"error": (completed.stderr or "").strip()[-800:]}
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": "risposta non valida: %r" % completed.stdout[-300:]}


def check(json_output: bool = False) -> int:
    python = _runtime_python()
    report = detect_system()
    if not python:
        report["status"] = "runtime_mancante"
        report["hint"] = (
            "Ripristina il runtime: python tools/bootstrap.py --restore <archivio>"
            if IS_WINDOWS
            else "Esegui: python tools/bootstrap.py --install"
        )
        print(json.dumps(report, indent=2) if json_output else _human(report))
        return 2
    probe = verify(python)
    report["probe"] = probe
    engine_ok = bool(probe.get("rvc_python") and probe.get("fairseq"))
    report["status"] = "ok" if engine_ok else "engine_incompleto"
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        _human(report)
    return 0 if engine_ok else 1


def _human(report: dict) -> str:
    lines = ["RVC Portable — verifica ambiente", ""]
    for key in ("os", "platform", "machine", "python", "runtime_python", "status"):
        lines.append("%-16s %s" % (key + ":", report.get(key, "")))
    probe = report.get("probe") or {}
    if probe:
        lines.append("")
        lines.append("%-16s %s" % ("motore:", "OK" if probe.get("rvc_python") and probe.get("fairseq") else "INCOMPLETO"))
        lines.append("%-16s %s" % ("python runtime:", probe.get("python", "?")))
        lines.append("%-16s %s" % ("torch:", probe.get("torch") or probe.get("torch_error", "?")))
        lines.append("%-16s %s" % ("cuda:", "si" if probe.get("cuda") else "no"))
        if probe.get("gpu"):
            lines.append("%-16s %s" % ("gpu:", probe["gpu"]))
        models = probe.get("base_models") or {}
        lines.append("%-16s %s" % ("pesi base:", ", ".join("%s %.0f MB" % (k, v / 1024 / 1024) for k, v in models.items()) or "MANCANTI"))
    for key in ("hint", "error"):
        if report.get(key):
            lines.append("")
            lines.append("%s: %s" % (key.upper(), report[key]))
    text = "\n".join(lines)
    print(text)
    return text


def install_windows(args) -> int:
    python = _runtime_python()
    if python:
        print("Runtime gia' presente: %s" % python)
        return check()
    if args.restore:
        archive = args.restore
        return _run(
            [
                sys.executable,
                os.path.join(ROOT, "tools", "restore_runtime_windows.py"),
                "--archive",
                archive,
                "--dest",
                "runtime",
            ]
        )
    print(
        "Nessun runtime trovato.\n"
        "Su Windows il runtime portatile (Python 3.9.13 + motore RVC) si scarica con:\n"
        "  setup.bat\n"
        "In alternativa, con un archivio locale:\n"
        "  set RVC_RUNTIME_ZIP=percorso\\runtime.zip  &&  setup.bat\n"
        "oppure ripristina un archivio storico:\n"
        "  python tools/bootstrap.py --restore <archivio-storico.zip>\n"
        "Su macOS/Linux:  python tools/bootstrap.py --install"
    )
    return 2


def _find_posix_python() -> Optional[str]:
    import shutil

    for name in ("python3.10", "python3.11", "python3"):
        found = shutil.which(name)
        if found:
            return found
    return None


def install_posix(args) -> int:
    python = _find_posix_python()
    if not python:
        print("Python 3.10+ non trovato. Installa Python (python.org o brew/apt) e riprova.")
        return 2
    venv_python = os.path.join(RUNTIME_DIR, "bin", "python3")
    if not os.path.isfile(venv_python):
        _run([python, "-m", "venv", RUNTIME_DIR])
    _run([venv_python, "-m", "pip", "install", "--upgrade", "pip<24.1", "wheel", "setuptools"])
    base = os.path.join(ROOT, "requirements", "base.txt")
    engine = os.path.join(ROOT, "requirements", "engine-posix.txt")
    wheelhouse = ""
    if args.offline:
        wheelhouse = "--no-index --find-links=%s" % os.path.abspath(args.offline)
    common = [venv_python, "-m", "pip", "install"]
    if wheelhouse:
        common += wheelhouse.split()
    _run(common + ["-r", base])
    torch_index = {
        "mps": ["--index-url", "https://download.pytorch.org/whl/cpu"],
        "cpu": ["--index-url", "https://download.pytorch.org/whl/cpu"],
        "cuda118": ["--index-url", "https://download.pytorch.org/whl/cu118"],
    }.get(args.profile)
    if args.profile == "cuda118":
        _run(common + torch_index + ["torch==2.2.2", "torchaudio==2.2.2", "torchvision==0.17.2"])
        _run(common + ["-r", engine])
    elif torch_index:
        _run(common + torch_index + ["torch==2.2.2", "torchaudio==2.2.2", "torchvision==0.17.2"])
        _run(common + ["-r", engine])
    else:
        _run(common + ["-r", engine])
    probe = verify(venv_python)
    if not (probe.get("rvc_python") and probe.get("fairseq")):
        print("Avvertenza: motore incompleto.")
        print(json.dumps(probe, indent=2))
        return 1
    print("Ambiente macOS/Linux pronto: %s" % venv_python)
    return 0


def install_dev(args) -> int:
    if IS_WINDOWS:
        runtime = _runtime_python()
        if not runtime:
            print("Runtime mancante: impossibile installare gli strumenti di sviluppo.")
            return 2
        os.makedirs(DEV_TARGET, exist_ok=True)
        _run(
            [
                runtime,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                "--target",
                DEV_TARGET,
                "pytest==7.4.4",
                "ruff==0.6.9",
            ]
        )
        with open(DEV_PTH, "w", encoding="ascii") as handle:
            handle.write("../../../.dev/site-packages\n")
        print("Strumenti di sviluppo installati in .dev/site-packages")
        return 0
    venv_python = _runtime_python()
    if not venv_python:
        print("Esegui prima --install.")
        return 2
    _run([venv_python, "-m", "pip", "install", "-r", os.path.join(ROOT, "requirements", "dev.txt")])
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Setup/verifica ambiente RVC Portable")
    parser.add_argument("--check", action="store_true", help="solo verifica (default)")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--install", action="store_true", help="installa/configura l'ambiente")
    parser.add_argument(
        "--profile",
        choices=("auto", "cpu", "cuda118", "mps"),
        default="auto",
        help="profilo acceleratore (POSIX)",
    )
    parser.add_argument("--offline", default=None, help="wheelhouse locale per install offline")
    parser.add_argument("--restore", default=None, help="archivio storico da cui ripristinare runtime (Windows)")
    parser.add_argument("--dev", action="store_true", help="installa pytest/ruff per lo sviluppo")
    args = parser.parse_args(argv)

    if args.dev:
        return install_dev(args)
    if args.install:
        return install_windows(args) if IS_WINDOWS else install_posix(args)
    return check(json_output=args.json)


if __name__ == "__main__":
    sys.exit(main())
