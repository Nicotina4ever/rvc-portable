"""Rilevamento hardware, interprete del motore e probe del runtime RVC.

Il backend **non importa torch**: il probe gira in un sottoprocesso del runtime
del motore e restituisce JSON. Cosi' l'avvio della UI resta leggero e il
backend e' lo stesso su Windows/macOS/Linux.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..paths import AppPaths

PROBE_TTL_S = 300.0
BASEMODEL_MIN_BYTES = 100 * 1024 * 1024

_probe_lock = threading.Lock()
_probe_cache: Dict[str, Tuple[float, "RuntimeProbe"]] = {}


def subprocess_kwargs() -> Dict[str, Any]:
    """Evita finestre console sui Windows quando si spawna un processo."""
    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return {"creationflags": flag}
    return {}


@dataclass
class RuntimeProbe:
    available: bool = False
    python_executable: str = ""
    python_version: str = ""
    torch: str = ""
    cuda: bool = False
    mps: bool = False
    gpu_name: str = ""
    vram_gb: Optional[float] = None
    engine_ok: bool = False
    fairseq_ok: bool = False
    base_models_dir: str = ""
    base_models: Dict[str, int] = field(default_factory=dict)
    base_models_missing: List[str] = field(default_factory=list)
    error: str = ""
    checked_at: float = 0.0
    stale: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "python_executable": self.python_executable,
            "python_version": self.python_version,
            "torch": self.torch,
            "torch_lt_26": _version_lt(self.torch, (2, 6)),
            "cuda": self.cuda,
            "mps": self.mps,
            "gpu_name": self.gpu_name,
            "vram_gb": self.vram_gb,
            "engine_ok": self.engine_ok,
            "fairseq_ok": self.fairseq_ok,
            "base_models_dir": self.base_models_dir,
            "base_models": self.base_models,
            "base_models_missing": self.base_models_missing,
            "error": self.error,
            "checked_at": self.checked_at,
            "stale": self.stale,
        }

    @property
    def base_models_ok(self) -> bool:
        return bool(self.base_models_dir) and not self.base_models_missing


PROBE_SCRIPT = r"""
import json, os, sys, importlib.util

out = {"python_executable": sys.executable, "python_version": sys.version.split()[0],
       "available": True, "torch": "", "cuda": False, "mps": False,
       "gpu_name": "", "vram_gb": None, "engine_ok": False, "fairseq_ok": False,
       "base_models_dir": "", "base_models": {}, "base_models_missing": [], "error": ""}

def _spec(name):
    try:
        return importlib.util.find_spec(name)
    except Exception:
        return None

engine_spec = _spec("rvc_python")
out["engine_ok"] = engine_spec is not None
out["fairseq_ok"] = _spec("fairseq") is not None

if engine_spec and getattr(engine_spec, "submodule_search_locations", None):
    base = os.path.join(list(engine_spec.submodule_search_locations)[0], "base_model")
    out["base_models_dir"] = base
    for name in ("hubert_base.pt", "rmvpe.pt"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            out["base_models"][name] = os.path.getsize(path)
        else:
            out["base_models_missing"].append(name)

try:
    import torch
    out["torch"] = str(torch.__version__)
    try:
        out["cuda"] = bool(torch.cuda.is_available())
    except Exception:
        out["cuda"] = False
    if out["cuda"]:
        try:
            out["gpu_name"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            out["vram_gb"] = round(float(props.total_memory) / (1024 ** 3), 1)
        except Exception as exc:
            out["error"] = "cuda-info: " + repr(exc)
    try:
        out["mps"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except Exception:
        out["mps"] = False
except Exception as exc:
    out["error"] = "torch: " + repr(exc)

print(json.dumps(out))
"""


def resolve_engine_python(paths: AppPaths) -> str:
    """Interprete usato dal motore: runtime bundled, altrimenti l'attuale."""
    runtime = paths.runtime_python
    if runtime and os.path.isfile(runtime):
        return runtime
    return sys.executable


def probe_engine(paths: AppPaths, force: bool = False, timeout: float = 180.0) -> RuntimeProbe:
    python = resolve_engine_python(paths)
    now = time.time()
    with _probe_lock:
        cached = _probe_cache.get(python)
    if cached and not force and (now - cached[0]) < PROBE_TTL_S:
        return cached[1]

    probe = RuntimeProbe(python_executable=python, checked_at=now)
    if not os.path.isfile(python):
        probe.error = "interprete non trovato: %s" % python
        _store(python, probe)
        return probe

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [python, "-B", "-c", PROBE_SCRIPT]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=paths.app_root,
            **subprocess_kwargs()
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        probe.error = "probe fallito: %s" % exc
        _store(python, probe)
        return probe

    if completed.returncode != 0:
        probe.error = "probe uscito con codice %s: %s" % (
            completed.returncode,
            (completed.stderr or "").strip()[-800:],
        )
        _store(python, probe)
        return probe

    try:
        data = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        probe.error = "risposta probe non valida: %s" % exc
        _store(python, probe)
        return probe

    probe.available = bool(data.get("available"))
    probe.python_executable = str(data.get("python_executable") or python)
    probe.python_version = str(data.get("python_version") or "")
    probe.torch = str(data.get("torch") or "")
    probe.cuda = bool(data.get("cuda"))
    probe.mps = bool(data.get("mps"))
    probe.gpu_name = str(data.get("gpu_name") or "")
    vram = data.get("vram_gb")
    probe.vram_gb = float(vram) if vram is not None else None
    probe.engine_ok = bool(data.get("engine_ok"))
    probe.fairseq_ok = bool(data.get("fairseq_ok"))
    probe.base_models_dir = str(data.get("base_models_dir") or "")
    probe.base_models = {
        str(k): int(v) for k, v in (data.get("base_models") or {}).items()
    }
    probe.base_models_missing = [str(x) for x in (data.get("base_models_missing") or [])]
    probe.error = str(data.get("error") or "")
    for name, size in probe.base_models.items():
        if size < BASEMODEL_MIN_BYTES:
            probe.base_models_missing.append("%s (troncato: %d byte)" % (name, size))
    _store(python, probe)
    return probe


def _store(python: str, probe: RuntimeProbe) -> None:
    with _probe_lock:
        _probe_cache[python] = (time.time(), probe)


def _version_lt(version: str, target: Tuple[int, ...]) -> bool:
    parts: List[int] = []
    for chunk in (version or "").split("+")[0].split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    if not parts:
        return False
    while len(parts) < len(target):
        parts.append(0)
    return tuple(parts[: len(target)]) < target


def effective_device(requested: str, probe: RuntimeProbe) -> Tuple[str, List[str]]:
    """Traduce la scelta utente in un device realmente utilizzabile."""
    requested = (requested or "auto").strip().lower()
    warnings: List[str] = []
    if requested == "auto":
        if probe.cuda:
            return "cuda:0", warnings
        if probe.mps:
            return "mps", warnings
        return "cpu", warnings
    if requested.startswith("cuda"):
        if probe.cuda:
            return requested, warnings
        warnings.append("CUDA non disponibile: uso CPU")
        return "cpu", warnings
    if requested == "mps":
        if probe.mps:
            return "mps", warnings
        warnings.append("MPS non disponibile: uso CPU")
        return "cpu", warnings
    return "cpu", warnings


def system_info() -> Dict[str, Any]:
    """CPU/RAM/OS senza dipendenze esterne."""
    info: Dict[str, Any] = {
        "platform": sys.platform,
        "os_name": os.name,
        "cpu_count": os.cpu_count(),
        "ram_gb": None,
        "machine": "",
    }
    try:
        if hasattr(os, "uname"):
            uname = os.uname()
            info["machine"] = uname.machine
    except Exception:
        pass
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            info["ram_gb"] = round(stat.ullTotalPhys / (1024 ** 3), 1)
        else:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            info["ram_gb"] = round(pages * page_size / (1024 ** 3), 1)
    except Exception:
        pass
    return info
