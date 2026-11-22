"""Esecuzione della pipeline di training a stadi.

Ogni stadio e' un processo separato che gira nella cartella del job con
``PYTHONPATH`` puntato al codice vendorizzato. Il backend parla con i processi
solo tramite righe di log stabili:

- ``PROGRESS <fatti> <totali>`` (preprocess, F0, HuBERT)
- ``RVC_EPOCH <n>`` e ``RVC_STEP <epoch> <percento>`` (training)
- ``loss_gen=...`` (loss del generatore)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

VENDOR_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "rvc")
BOOT_SCRIPT = os.path.join(VENDOR_ROOT, "_boot.py")
MUTE_DIR = os.path.join(VENDOR_ROOT, "assets", "mute")

PROGRESS_RE = re.compile(r"^PROGRESS\s+(\d+)\s+(\d+)")
EPOCH_RE = re.compile(r"^RVC_EPOCH\s+(\d+)")
STEP_RE = re.compile(r"^RVC_STEP\s+(\d+)\s+(\d+)")
LOSS_RE = re.compile(r"loss_gen=([0-9]*\.?[0-9]+)")

STAGE_LABELS = {
    "preprocess": "Taglio e ricampionamento",
    "f0": "Estrazione F0",
    "hubert": "Estrazione feature HuBERT",
    "filelist": "Preparazione liste",
    "train": "Training",
    "index": "Indice FAISS",
    "finalize": "Salvataggio modello",
}


def resolve_python(paths) -> str:
    """Preferisce il Python del runtime portatile (deve avere torch/faiss)."""
    runtime = getattr(paths, "runtime_dir", "")
    if runtime:
        for name in ("python.exe", "python"):
            candidate = os.path.join(runtime, name)
            if os.path.isfile(candidate):
                return candidate
    return sys.executable


def build_env(paths, job_dir: str, exp_dir: str, assets: Dict[str, Any], nproc: int) -> Dict[str, str]:
    env = os.environ.copy()
    parts = [VENDOR_ROOT, paths.app_root]
    existing = env.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["RVC_HUBERT_PATH"] = str(assets.get("hubert") or "")
    env["RVC_RMVPE_PATH"] = str(assets.get("rmvpe") or "")
    env["RVC_TRAIN_WEIGHTS_DIR"] = os.path.join(job_dir, "weights")
    env["RVC_TRAIN_METRICS"] = os.path.join(exp_dir, "metrics.jsonl")
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["OMP_NUM_THREADS"] = str(max(1, int(nproc)))
    env["MKL_NUM_THREADS"] = str(max(1, int(nproc)))
    return env


def _sr_label(sample_rate: int) -> str:
    return "%dk" % (int(sample_rate) // 1000)


def _module_command(python: str, module: str, args: List[Any]) -> List[str]:
    """Comando che passa dal bootstrap ``_boot.py`` (il runtime e' in modalita' isolata)."""
    return [python, BOOT_SCRIPT, module] + [str(item) for item in args]


def build_command(stage: str, ctx: Dict[str, Any]) -> List[str]:
    python = ctx["python"]
    exp_dir = ctx["exp_dir"]
    exp_name = ctx["exp_name"]
    settings = ctx["settings"]
    if stage == "preprocess":
        return _module_command(
            python,
            "train.preprocess",
            [
                ctx["raw_dir"],
                int(settings["sample_rate"]),
                int(ctx.get("nproc") or 2),
                exp_dir,
                "False",
                "3.7",
            ],
        )
    if stage == "f0":
        return _module_command(
            python,
            "train.dataset.extract_f0",
            [
                exp_dir,
                str(settings.get("f0_method") or "rmvpe"),
                "cuda" if settings.get("device") != "cpu" else "cpu",
                "true" if settings.get("device") != "cpu" else "false",
            ],
        )
    if stage == "hubert":
        return _module_command(
            python,
            "train.dataset.extract_hubert_feature",
            [
                exp_dir,
                str(settings.get("version") or "v2"),
                "cuda" if settings.get("device") != "cpu" else "cpu",
                "true" if settings.get("device") != "cpu" else "false",
            ],
        )
    if stage == "train":
        return _module_command(
            python,
            "train.train",
            [
                "-se",
                int(settings["save_every"]),
                "-te",
                int(settings["epochs"]),
                "-pg",
                ctx["pretrained_g"],
                "-pd",
                ctx["pretrained_d"],
                "-g",
                "0",
                "-bs",
                int(settings["batch_size"]),
                "-e",
                exp_name,
                "-sr",
                _sr_label(settings["sample_rate"]),
                "-sw",
                "1",
                "-v",
                str(settings.get("version") or "v2"),
                "-f0",
                "1" if settings.get("f0") else "0",
                "-l",
                "1",
                "-c",
                "0",
            ],
        )
    if stage == "index":
        return _module_command(
            python,
            "train.train_index",
            [
                exp_name,
                str(settings.get("version") or "v2"),
                os.path.join(ctx["job_dir"], "output"),
                max(1, int(ctx.get("nproc") or 2)),
            ],
        )
    raise ValueError("stadio sconosciuto: %s" % stage)


def kill_process_tree(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        except OSError:
            pass
    try:
        proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass


def run_stage(
    command: List[str],
    cwd: str,
    env: Dict[str, str],
    log_path: str,
    on_line: Callable[[str], None],
    cancel_event: Optional[threading.Event] = None,
    register_process: Optional[Callable[[Optional[subprocess.Popen]], None]] = None,
    timeout_s: Optional[float] = None,
) -> int:
    """Esegue un comando, inoltra le righe di log e restituisce il codice di uscita."""
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with open(log_path, "a", encoding="utf-8", errors="replace") as log_handle:
        log_handle.write("\n$ %s\n" % " ".join(command))
        log_handle.flush()
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
        except OSError as exc:
            log_handle.write("avvio fallito: %s\n" % exc)
            return 127
        if register_process:
            register_process(proc)

        started = time.time()

        def _reader() -> None:
            stream = proc.stdout
            if stream is None:
                return
            for raw in stream:
                line = raw.rstrip("\r\n")
                log_handle.write(line + "\n")
                log_handle.flush()
                try:
                    on_line(line)
                except Exception:
                    pass

        reader = threading.Thread(target=_reader, name="rvc-train-log", daemon=True)
        reader.start()
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    kill_process_tree(proc)
                    break
                if timeout_s is not None and (time.time() - started) > timeout_s:
                    log_handle.write("timeout dello stadio\n")
                    kill_process_tree(proc)
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
            reader.join(timeout=5.0)
            code = proc.poll()
            if code is None:
                kill_process_tree(proc)
                code = proc.poll()
            return int(code if code is not None else 1)
        finally:
            if register_process:
                register_process(None)
