"""Diagnostica dell'ambiente: trasforma errori silenziosi in azioni guidate."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import __version__
from .core import devices
from .paths import AppPaths
from .settings import Settings

OK = "ok"
WARN = "warn"
FAIL = "fail"
INFO = "info"


@dataclass
class Check:
    id: str
    label: str
    status: str
    detail: str = ""
    fix: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "fix": self.fix,
            "params": self.params,
        }


def _version_tuple(version: str) -> tuple:
    parts: List[int] = []
    for chunk in (version or "").split("+")[0].split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def run_checks(
    paths: AppPaths,
    settings: Settings,
    force_probe: bool = False,
    probe: Optional[devices.RuntimeProbe] = None,
) -> Dict[str, Any]:
    probe = probe or devices.probe_engine(paths, force=force_probe)
    checks: List[Check] = []

    # ------------------------------------------------------------- runtime
    checks.append(
        Check(
            id="runtime_python",
            label="Interprete del motore",
            status=OK if probe.python_executable and os.path.isfile(probe.python_executable) else FAIL,
            detail="%s (Python %s)" % (probe.python_executable, probe.python_version or "?"),
            fix="Ripristina il runtime con tools/restore_runtime_windows.py oppure esegui tools/bootstrap.py",
            params={"path": probe.python_executable, "version": probe.python_version},
        )
    )

    py_version = _version_tuple(probe.python_version)
    if not py_version:
        py_status, py_detail = WARN, "versione non rilevata"
    elif py_version < (3, 9):
        py_status, py_detail = FAIL, "serve Python >= 3.9"
    elif py_version >= (3, 12):
        py_status, py_detail = (
            WARN,
            "Python %s: il motore rvc-python e' verificato su 3.9/3.10"
            % probe.python_version,
        )
    else:
        py_status, py_detail = OK, "Python %s compatibile" % probe.python_version
    checks.append(
        Check(
            id="python_version",
            label="Versione Python",
            status=py_status,
            detail=py_detail,
            fix="Usa il runtime portatile (Python 3.9.13) incluso nella distribuzione",
        )
    )

    # ---------------------------------------------------------------- torch
    if not probe.torch:
        checks.append(
            Check(
                id="torch",
                label="PyTorch",
                status=FAIL,
                detail=probe.error or "torch non importabile",
                fix="Reinstalla il runtime portatile o esegui tools/bootstrap.py",
            )
        )
    else:
        torch_lt_26 = devices._version_lt(probe.torch, (2, 6))  # noqa: SLF001
        checks.append(
            Check(
                id="torch",
                label="PyTorch",
                status=OK if torch_lt_26 else FAIL,
                detail="torch %s%s"
                % (probe.torch, "" if torch_lt_26 else " (>= 2.6: incompatible con fairseq)"),
                fix="Mantieni torch < 2.6: il caricamento dei checkpoint fairseq richiede weights_only=False",
                params={"version": probe.torch, "lt_26": torch_lt_26},
            )
        )

    # ----------------------------------------------------------------- cuda
    if probe.cuda:
        checks.append(
            Check(
                id="cuda",
                label="Accelerazione CUDA",
                status=OK,
                detail="%s — %.1f GB VRAM" % (probe.gpu_name or "GPU", probe.vram_gb or 0.0),
                params={"gpu": probe.gpu_name, "vram_gb": probe.vram_gb},
            )
        )
    elif probe.mps:
        checks.append(
            Check(
                id="cuda",
                label="Accelerazione",
                status=WARN,
                detail="MPS disponibile (sperimentale per RVC); fallback CPU consigliato",
                params={"mps": True},
            )
        )
    else:
        checks.append(
            Check(
                id="cuda",
                label="Accelerazione CUDA",
                status=INFO,
                detail="Nessuna GPU CUDA rilevata: inferenza su CPU (piu' lenta)",
                fix="Su Windows installa i driver NVIDIA aggiornati",
            )
        )

    # --------------------------------------------------------------- engine
    checks.append(
        Check(
            id="engine",
            label="Motore rvc-python",
            status=OK if probe.engine_ok else FAIL,
            detail="rvc_python importabile" if probe.engine_ok else "rvc_python non installato",
            fix="Ripristina il runtime portatile (include rvc-python 0.1.5)",
        )
    )
    checks.append(
        Check(
            id="fairseq",
            label="Fairseq",
            status=OK if probe.fairseq_ok else FAIL,
            detail="fairseq 0.12.2 importabile" if probe.fairseq_ok else "fairseq non installato",
            fix="Ripristina il runtime portatile (include fairseq 0.12.2)",
        )
    )

    if probe.base_models_ok:
        size_mb = sum(probe.base_models.values()) / (1024 * 1024)
        checks.append(
            Check(
                id="base_models",
                label="Pesi base (HuBERT/RMVPE)",
                status=OK,
                detail="%.0f MB in %s" % (size_mb, probe.base_models_dir),
                params={"files": probe.base_models},
            )
        )
    else:
        checks.append(
            Check(
                id="base_models",
                label="Pesi base (HuBERT/RMVPE)",
                status=FAIL,
                detail="mancanti o troncati: %s"
                % (", ".join(probe.base_models_missing) or "cartella non trovata"),
                fix="Ripristina il runtime portatile: i pesi base sono inclusi e non richiedono rete",
            )
        )

    # ------------------------------------------------------------ settings
    problems = settings.validate_paths()
    if not problems:
        checks.append(
            Check(
                id="paths",
                label="Percorsi configurati",
                status=OK,
                detail="cartelle e modello raggiungibili",
            )
        )
    else:
        checks.append(
            Check(
                id="paths",
                label="Percorsi configurati",
                status=WARN,
                detail="; ".join(
                    "%s (%s)" % (item["field"], item["reason"]) for item in problems
                ),
                fix="Apri Configurazione e seleziona cartelle/modello validi",
                params={"problems": problems},
            )
        )

    # ------------------------------------------------------------- storage
    try:
        usage = shutil.disk_usage(paths.data_dir)
        free_gb = usage.free / (1024 ** 3)
        checks.append(
            Check(
                id="disk_free",
                label="Spazio disco",
                status=OK if free_gb >= 2 else WARN,
                detail="%.1f GB liberi in %s" % (free_gb, paths.data_dir),
                fix="Libera spazio: i file audio e i modelli occupano spazio",
                params={"free_gb": round(free_gb, 1)},
            )
        )
    except OSError as exc:
        checks.append(
            Check(
                id="disk_free",
                label="Spazio disco",
                status=WARN,
                detail="impossibile leggere lo spazio: %s" % exc,
            )
        )

    writable = _test_writable(paths.data_dir)
    checks.append(
        Check(
            id="data_writable",
            label="Cartella dati scrivibile",
            status=OK if writable else FAIL,
            detail=paths.data_dir,
            fix="Sposta l'app in una cartella scrivibile o usa --data-dir",
        )
    )

    # ---------------------------------------------------------------- web/ui
    index_path = os.path.join(paths.web_dir, "index.html")
    checks.append(
        Check(
            id="web_assets",
            label="Interfaccia web",
            status=OK if os.path.isfile(index_path) else FAIL,
            detail=index_path,
            fix="Reinstalla i file dell'applicazione (cartella web/)",
        )
    )

    # --------------------------------------------------------------- cloud
    dropbox_configured = bool(settings.cloud.dropbox.app_key)
    checks.append(
        Check(
            id="dropbox",
            label="Dropbox",
            status=INFO,
            detail="App Key configurata" if dropbox_configured else "non configurato (opzionale)",
            fix="Tab Cloud: incolla la App Key della tua app Dropbox",
        )
    )

    # --------------------------------------------------------------- android
    if settings.android.enabled or settings.android.shared_dir:
        shared = settings.android.shared_dir
        issues = []
        if not shared:
            issues.append("cartella condivisa non impostata")
        elif not os.path.isdir(shared):
            issues.append("cartella condivisa non trovata: %s" % shared)
        else:
            try:
                from .android_bridge import read_models_count, shared_paths

                paths_info = shared_paths(shared, settings.android)
                for key, label in (("input_dir", "AudioIn"), ("output_dir", "AudioOut")):
                    if not os.path.isdir(paths_info[key]):
                        issues.append("%s mancante" % label)
                if not os.path.isfile(paths_info["models_path"]):
                    issues.append("modelli.txt mancante")
                elif read_models_count(paths_info["models_path"]) == 0:
                    issues.append("modelli.txt senza modelli")
            except Exception as exc:  # pragma: no cover - difensivo
                issues.append(str(exc))
        checks.append(
            Check(
                id="android",
                label="Ponte Android/Dropbox",
                status=WARN if issues else OK,
                detail="; ".join(issues) if issues else "cartella condivisa pronta",
                fix="Tab Cloud: riattiva il preset Android per ricreare cartelle e modelli.txt",
            )
        )
    else:
        checks.append(
            Check(
                id="android",
                label="Ponte Android/Dropbox",
                status=INFO,
                detail="non attivo (opzionale): abilitalo dal tab Cloud",
                fix="Tab Cloud: scegli la cartella Dropbox condivisa e premi 'Attiva preset'",
            )
        )

    # --------------------------------------------------------------- summary
    counts = {OK: 0, WARN: 0, FAIL: 0, INFO: 0}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    if counts[FAIL]:
        overall = FAIL
    elif counts[WARN]:
        overall = WARN
    else:
        overall = OK

    return {
        "overall": overall,
        "counts": counts,
        "checks": [check.to_dict() for check in checks],
        "environment": {
            "app_version": __version__,
            "platform": sys.platform,
            "system": devices.system_info(),
            "paths": paths.describe(),
            "engine_python": probe.python_executable,
            "probe": probe.to_dict(),
        },
    }


def _test_writable(directory: str) -> bool:
    try:
        os.makedirs(directory, exist_ok=True)
        probe_file = os.path.join(directory, ".doctor-write-test")
        with open(probe_file, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe_file)
        return True
    except OSError:
        return False


def summary_text(report: Dict[str, Any]) -> str:
    lines = ["RVC Portable — Diagnostica", ""]
    for check in report.get("checks", []):
        marker = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]", "info": "[INFO]"}.get(
            check["status"], "[?]   "
        )
        lines.append("%s %-28s %s" % (marker, check["label"], check["detail"]))
        if check.get("fix") and check["status"] in (WARN, FAIL):
            lines.append("       fix: %s" % check["fix"])
    lines.append("")
    lines.append("Esito: %s" % report.get("overall", "?").upper())
    return "\n".join(lines)
