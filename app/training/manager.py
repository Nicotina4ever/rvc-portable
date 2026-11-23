"""Servizio di addestramento: coda, stato persistente, esecuzione della pipeline."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from . import assets as assets_module
from . import dataset as dataset_module
from . import pipeline
from .filelist import build_filelist
from .presets import DEFAULT_PRESET, get_preset, preset_list

STATE_VERSION = 1
MAX_JOBS = 80
DISK_MARGIN_BYTES = 2 * 1024 * 1024 * 1024
CACHE_GT = "0_gt_wavs"
CACHE_16K = "1_16k_wavs"
CACHE_F0 = "2a_f0"
CACHE_F0NSF = "2b-f0nsf"
CACHE_FEATURES = ("3_feature256", "3_feature768")

STAGE_RANGES = {
    "dataset": (0.0, 4.0),
    "assets": (4.0, 8.0),
    "preprocess": (8.0, 22.0),
    "f0": (22.0, 38.0),
    "hubert": (38.0, 54.0),
    "filelist": (54.0, 56.0),
    "train": (56.0, 94.0),
    "evaluate": (94.0, 97.0),
    "index": (97.0, 99.0),
    "finalize": (99.0, 100.0),
}

STAGE_TIMEOUTS = {
    "preprocess": 3 * 3600.0,
    "f0": 3 * 3600.0,
    "hubert": 3 * 3600.0,
    "train": 24 * 3600.0,
    "index": 3 * 3600.0,
}


class TrainingError(RuntimeError):
    def __init__(self, message: str, code: str = "training_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-._")
    return text[:48] or "modello"


class TrainingService:
    """Un solo job attivo; gli altri restano in coda FIFO."""

    def __init__(self, paths, settings_manager, job_queue=None, bus=None) -> None:
        self.paths = paths
        self.settings_manager = settings_manager
        self.job_queue = job_queue
        self.bus = bus
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self._pending: Deque[str] = deque()
        self._worker: Optional[threading.Thread] = None
        self._cancel_events: Dict[str, threading.Event] = {}
        self._processes: Dict[str, subprocess.Popen] = {}
        self._cuda_cache: Dict[str, Any] = {}
        self._cuda_cache_ts = 0.0
        os.makedirs(self.root_dir, exist_ok=True)
        os.makedirs(self.jobs_dir, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------ paths
    @property
    def root_dir(self) -> str:
        return self.paths.training_dir

    @property
    def jobs_dir(self) -> str:
        return os.path.join(self.root_dir, "jobs")

    @property
    def state_path(self) -> str:
        return os.path.join(self.root_dir, "state.json")

    # ------------------------------------------------------------------ cache
    def _cache_paths(self, job: Dict[str, Any]) -> List[str]:
        job_dir = job.get("dir") or ""
        exp_name = job.get("exp_name") or ""
        paths = [
            os.path.join(job_dir, "dataset"),
            os.path.join(job_dir, "weights"),
            os.path.join(job_dir, "eval"),
            os.path.join(job_dir, "output"),
            os.path.join(job_dir, "base"),
        ]
        if exp_name:
            exp_dir = os.path.join(job_dir, "logs", exp_name)
            paths.append(exp_dir)
        return [path for path in paths if os.path.isdir(path)]

    def _size_of(self, paths: List[str]) -> int:
        total = 0
        for path in paths:
            for base, _dirs, names in os.walk(path):
                for name in names:
                    try:
                        total += os.path.getsize(os.path.join(base, name))
                    except OSError:
                        pass
        return total

    def cache_bytes(self) -> int:
        with self._lock:
            jobs = [dict(self._jobs[job_id]) for job_id in self._order if job_id in self._jobs]
        total = 0
        for job in jobs:
            total += self._size_of(self._cache_paths(job))
        return total

    def clean_job_cache(self, job_id: str) -> Dict[str, Any]:
        job_id = str(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise TrainingError("job non trovato", "training_not_found")
            if job.get("status") in ("running", "queued"):
                raise TrainingError(
                    "Annulla o attendi la fine del training prima di pulire la cache.",
                    "training_busy",
                )
            paths = self._cache_paths(job)
            before = self._size_of(paths)
        removed = 0
        for path in paths:
            try:
                shutil.rmtree(path)
                removed += 1
            except OSError:
                pass
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["cache_cleaned_at"] = time.time()
                job["cache_freed_mb"] = round(before / (1024 * 1024), 1)
                job["resumable"] = False
                job["message"] = "Cache del training eliminata"
                self._save()
        self._append_log(
            os.path.join(job.get("dir") or "", "log.txt"),
            "cache rimossa: %.1f MB (%d cartelle)" % (before / (1024 * 1024), removed),
        )
        return {"job": self.get_job(job_id) or {}, "freed_mb": round(before / (1024 * 1024), 1)}

    def clean_terminal_caches(self) -> Dict[str, Any]:
        with self._lock:
            ids = [
                job_id
                for job_id in self._order
                if self._jobs.get(job_id, {}).get("status") in ("completed", "failed", "canceled")
            ]
        total = 0.0
        cleaned = 0
        for job_id in ids:
            try:
                result = self.clean_job_cache(job_id)
                total += float(result.get("freed_mb") or 0.0)
                cleaned += 1
            except TrainingError:
                continue
        return {"cleaned": cleaned, "freed_mb": round(total, 1)}

    # ------------------------------------------------------------- persistence
    def _load(self) -> None:
        path = self.state_path
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, dict):
            return
        changed = False
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if job.get("status") in ("queued", "running"):
                job["status"] = "failed"
                job["error"] = "Interrotto dal riavvio dell'applicazione"
                job["finished_at"] = time.time()
                changed = True
            self._jobs[job_id] = job
            self._order.append(job_id)
        if changed:
            self._save()

    def _save(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "jobs": {job_id: self._jobs[job_id] for job_id in self._order if job_id in self._jobs},
        }
        tmp = self.state_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    def _trim(self) -> None:
        while len(self._order) > MAX_JOBS:
            oldest = self._order.pop(0)
            self._jobs.pop(oldest, None)
            self._cancel_events.pop(oldest, None)
            self._processes.pop(oldest, None)

    # ------------------------------------------------------------------ events
    def _publish(self, job: Dict[str, Any]) -> None:
        if self.bus is None:
            return
        try:
            self.bus.publish(
                "training",
                {
                    "id": job.get("id"),
                    "name": job.get("name"),
                    "status": job.get("status"),
                    "stage": job.get("stage"),
                    "progress": job.get("progress"),
                    "epoch": job.get("epoch"),
                    "total_epochs": job.get("total_epochs"),
                    "loss": job.get("loss"),
                    "message": job.get("message"),
                    "error": job.get("error"),
                },
            )
        except Exception:  # pragma: no cover - difensivo
            pass

    def _update(self, job_id: str, persist: bool = False, **fields) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {}
            job.update(fields)
            if persist:
                self._save()
            snapshot = dict(job)
        self._publish(snapshot)
        return snapshot

    # ------------------------------------------------------------ capabilities
    def _probe_cuda(self) -> Dict[str, Any]:
        now = time.time()
        if self._cuda_cache and (now - self._cuda_cache_ts) < 300:
            return self._cuda_cache
        python = pipeline.resolve_python(self.paths)
        script = (
            "import json,sys\n"
            "try:\n"
            " import torch\n"
            " info={'available': bool(torch.cuda.is_available()),"
            " 'count': int(torch.cuda.device_count() if torch.cuda.is_available() else 0),"
            " 'name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else '',"
            " 'vram_gb': round(torch.cuda.get_device_properties(0).total_memory/1024**3,1) if torch.cuda.is_available() else 0.0,"
            " 'torch': torch.__version__}\n"
            "except Exception as exc:\n"
            " info={'available': False, 'count': 0, 'name': '', 'vram_gb': 0.0, 'torch': '', 'error': str(exc)}\n"
            "print(json.dumps(info))\n"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            result = subprocess.run(
                [python, "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=40,
                creationflags=flags,
            )
            data = json.loads((result.stdout or "").strip().splitlines()[-1])
        except Exception as exc:
            data = {"available": False, "count": 0, "name": "", "vram_gb": 0.0, "error": str(exc)}
        self._cuda_cache = data
        self._cuda_cache_ts = now
        return data

    def capabilities(self) -> Dict[str, Any]:
        training = self.settings_manager.settings.training
        settings_dict = training.dict()
        asset_info = assets_module.assets_status(
            self.paths,
            self.settings_manager.settings,
            settings_dict["sample_rate"],
            bool(settings_dict["f0"]),
            settings_dict["version"],
        )
        disk = shutil.disk_usage(self.paths.data_dir)
        cuda = self._probe_cuda()
        return {
            "enabled": bool(training.enabled),
            "python": pipeline.resolve_python(self.paths),
            "vendor": pipeline.VENDOR_ROOT,
            "cuda": cuda,
            "disk_free_gb": round(disk.free / 1024**3, 1),
            "training_used_gb": round(sum(self._size_of(self._cache_paths(dict(self._jobs[job_id]))) for job_id in self._order if job_id in self._jobs) / 1024**3, 2),
            "assets": asset_info,
            "presets": preset_list(),
            "defaults": settings_dict,
            "active": self.active_id(),
            "pending": len(self._pending),
        }

    # ------------------------------------------------------------------- queue
    def active_id(self) -> Optional[str]:
        with self._lock:
            for job_id in self._order:
                if self._jobs.get(job_id, {}).get("status") == "running":
                    return job_id
        return None

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(self._jobs[job_id]) for job_id in reversed(self._order) if job_id in self._jobs]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return dict(job) if job else None

    def log_tail(self, job_id: str, offset: int = 0, limit: int = 200) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise TrainingError("job non trovato", "training_not_found")
        path = os.path.join(job["dir"], "log.txt")
        lines: List[str] = []
        total = 0
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    all_lines = handle.readlines()
                total = len(all_lines)
                lines = [line.rstrip("\n") for line in all_lines[offset : offset + limit]]
            except OSError:
                pass
        return {"offset": offset, "total": total, "lines": lines}

    # ------------------------------------------------------------------- start
    def start(self, request: Dict[str, Any]) -> Dict[str, Any]:
        training = self.settings_manager.settings.training
        if not training.enabled:
            raise TrainingError("Addestramento disattivato nelle impostazioni", "training_disabled")
        with self._lock:
            busy = any(
                self._jobs.get(job_id, {}).get("status") in ("queued", "running")
                for job_id in self._order
            )
        if busy:
            raise TrainingError(
                "C'e' gia' un training in corso o in coda: attendi o annullalo.",
                "training_busy",
            )

        source = str((request or {}).get("source") or "").strip()
        if not source:
            raise TrainingError("Scegli un dataset (cartella o ZIP)", "training_source_missing")
        try:
            quick = dataset_module.quick_check(source)
        except dataset_module.DatasetError as exc:
            raise TrainingError(str(exc), "training_dataset_invalid")

        name = str((request or {}).get("name") or "").strip() or "Modello"
        preset = get_preset((request or {}).get("preset") or DEFAULT_PRESET)
        settings = self._resolve_settings(training.dict(), preset.to_dict(), (request or {}).get("overrides"))

        disk = shutil.disk_usage(self.paths.data_dir)
        if disk.free < DISK_MARGIN_BYTES:
            raise TrainingError(
                "Spazio disco insufficiente: libera almeno 2 GB in data/", "training_disk_low"
            )

        job_id = uuid.uuid4().hex[:12]
        exp_name = slugify(name)
        job_dir = os.path.join(self.jobs_dir, job_id)
        for sub in ("dataset", "logs", "weights", "output", "state"):
            os.makedirs(os.path.join(job_dir, sub), exist_ok=True)

        job: Dict[str, Any] = {
            "id": job_id,
            "name": name,
            "exp_name": exp_name,
            "test_sample": str((request or {}).get("test_sample") or "").strip(),
            "evaluate_checkpoints": bool((request or {}).get("evaluate_checkpoints", True)),
            "finetune_model": str((request or {}).get("finetune_model") or "").strip(),
            "dir": job_dir,
            "source": os.path.abspath(source),
            "dataset_quick": quick,
            "dataset": {},
            "settings": settings,
            "preset": preset.id,
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "epoch": 0,
            "total_epochs": int(settings["epochs"]),
            "loss": None,
            "message": "In attesa",
            "error": "",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "stages": {},
            "output": {},
        }
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._cancel_events[job_id] = threading.Event()
            self._pending.append(job_id)
            self._trim()
            self._save()
            need_worker = self._worker is None or not self._worker.is_alive()
            if need_worker:
                self._worker = threading.Thread(
                    target=self._worker_loop, name="rvc-training", daemon=True
                )
                self._worker.start()
        self._publish(job)
        return job

    def _resolve_settings(
        self, defaults: Dict[str, Any], preset: Dict[str, Any], overrides: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        overrides = overrides if isinstance(overrides, dict) else {}
        merged = {
            "sample_rate": int(overrides.get("sample_rate", defaults.get("sample_rate", 48000))),
            "version": str(overrides.get("version", defaults.get("version", "v2"))).lower(),
            "f0": bool(overrides.get("f0", defaults.get("f0", True))),
            "f0_method": str(overrides.get("f0_method", defaults.get("f0_method", "rmvpe"))).lower(),
            "epochs": int(overrides.get("epochs", preset.get("epochs", 250))),
            "batch_size": int(overrides.get("batch_size", preset.get("batch_size", 6))),
            "save_every": int(overrides.get("save_every", preset.get("save_every", 20))),
            "keep_intermediate": bool(
                overrides.get("keep_intermediate", defaults.get("keep_intermediate", True))
            ),
            "exclusive_gpu": bool(
                overrides.get("exclusive_gpu", defaults.get("exclusive_gpu", True))
            ),
            "device": "cpu" if overrides.get("device") == "cpu" else "cuda",
        }
        if merged["sample_rate"] not in (32000, 40000, 48000):
            raise TrainingError("Sample rate non valido", "training_settings_invalid")
        if merged["version"] not in ("v1", "v2"):
            raise TrainingError("Versione non valida", "training_settings_invalid")
        if merged["epochs"] < 10 or merged["epochs"] > 2000:
            raise TrainingError("Epoche fuori intervallo (10-2000)", "training_settings_invalid")
        if merged["batch_size"] < 1 or merged["batch_size"] > 64:
            raise TrainingError("Batch size fuori intervallo (1-64)", "training_settings_invalid")
        if merged["version"] == "v2" and merged["sample_rate"] == 40000:
            merged["version"] = "v1"  # 40k non esiste per v2
        return merged

    def cancel(self, job_id: str) -> Dict[str, Any]:
        job_id = str(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise TrainingError("job non trovato", "training_not_found")
            if job["status"] in ("completed", "failed", "canceled"):
                return dict(job)
            event = self._cancel_events.setdefault(job_id, threading.Event())
            event.set()
            if job_id in self._pending:
                try:
                    self._pending.remove(job_id)
                except ValueError:
                    pass
                job["status"] = "canceled"
                job["stage"] = "canceled"
                job["message"] = "Annullato"
                job["finished_at"] = time.time()
                self._save()
            proc = self._processes.get(job_id)
        if proc is not None:
            pipeline.kill_process_tree(proc)
        self._update(job_id, message="Annullamento in corso...")
        return self.get_job(job_id) or {}

    def resume(self, job_id: str) -> Dict[str, Any]:
        job_id = str(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise TrainingError("job non trovato", "training_not_found")
            if job["status"] not in ("failed", "canceled"):
                raise TrainingError(
                    "Si puo' riprendere solo un job fallito o annullato", "training_resume_invalid"
                )
            if any(
                self._jobs.get(other, {}).get("status") in ("queued", "running")
                for other in self._order
            ):
                raise TrainingError(
                    "C'e' gia' un training attivo: attendi o annullalo.",
                    "training_busy",
                )
            job.update(
                status="queued",
                stage="queued",
                progress=0.0,
                message="In coda (ripresa)",
                error="",
                finished_at=None,
            )
            self._cancel_events[job_id] = threading.Event()
            self._pending.append(job_id)
            self._save()
            need_worker = self._worker is None or not self._worker.is_alive()
            if need_worker:
                self._worker = threading.Thread(
                    target=self._worker_loop, name="rvc-training", daemon=True
                )
                self._worker.start()
        self._publish(job)
        return job

    # ------------------------------------------------------------------ worker
    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                job_id = self._pending.popleft()
            try:
                self._run(job_id)
            except Exception as exc:  # pragma: no cover - difensivo
                self._update(
                    job_id,
                    persist=True,
                    status="failed",
                    stage="failed",
                    error=str(exc),
                    message="Errore imprevisto",
                    finished_at=time.time(),
                )

    # --------------------------------------------------------------- execution
    def _run(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None:
            return
        cancel = self._cancel_events.setdefault(job_id, threading.Event())
        job_dir = job["dir"]
        log_path = os.path.join(job_dir, "log.txt")
        self._append_log(log_path, "=== Job %s: %s ===" % (job["id"], job["name"]))
        try:
            self._append_log(
                log_path,
                "Parametri: %s" % json.dumps(job.get("settings") or {}, ensure_ascii=False, sort_keys=True),
            )
        except (TypeError, ValueError):
            pass
        self._update(
            job_id,
            persist=True,
            status="running",
            stage="dataset",
            started_at=time.time(),
            message="Preparazione dataset",
            progress=0.0,
        )

        held_queue = False
        try:
            settings = job["settings"]
            if settings.get("exclusive_gpu") and self.job_queue is not None:
                self._wait_for_idle_queue(cancel)
                self.job_queue.hold("training %s" % job["name"])
                held_queue = True

            # 1) dataset
            if cancel.is_set():
                raise TrainingError("Annullato", "training_canceled")
            raw_dir = os.path.join(job_dir, "dataset", "raw")
            report = dataset_module.prepare_dataset(job["source"], raw_dir)
            self._append_log(
                log_path,
                "Dataset: %d file, %.1f min, %s"
                % (report["files"], report["total_s"] / 60.0, report.get("sample_rates")),
            )
            self._update(
                job_id,
                dataset={key: report.get(key) for key in ("files", "total_s", "min_s", "max_s", "sample_rates", "warnings", "errors", "ready")},
                progress=self._stage_progress("dataset", 1.0),
                message="Dataset pronto",
            )
            if not report.get("ready"):
                raise TrainingError(
                    "; ".join(report.get("errors") or ["dataset non valido"]),
                    "training_dataset_invalid",
                )

            # 2) assets
            self._update(job_id, stage="assets", message="Verifica pesi base", progress=self._stage_progress("assets", 0.2))
            asset_info = assets_module.ensure_pretrained(
                self.paths,
                self.settings_manager.settings,
                settings["sample_rate"],
                bool(settings["f0"]),
                settings["version"],
                on_log=lambda message: self._append_log(log_path, message),
            )
            hubert = assets_module.resolve_runtime_model("hubert_base.pt", self.paths)
            rmvpe = assets_module.resolve_runtime_model("rmvpe.pt", self.paths)
            if not hubert or not rmvpe:
                raise TrainingError(
                    "hubert_base.pt o rmvpe.pt assenti nel runtime: reinstalla il runtime portatile",
                    "training_assets_missing",
                )
            if not asset_info.get("complete"):
                raise TrainingError(
                    "Pesi pre-addestrati mancanti: %s" % ", ".join(asset_info.get("missing") or []),
                    "training_assets_missing",
                )
            assets_ctx = {
                "hubert": hubert,
                "rmvpe": rmvpe,
                "g": asset_info["found"]["g"],
                "d": asset_info["found"]["d"],
            }
            finetune_model = str(job.get("finetune_model") or "").strip()
            if finetune_model:
                prepared = self._prepare_finetune(job, job_dir, finetune_model, log_path)
                if prepared:
                    assets_ctx["g"] = prepared
            self._update(job_id, progress=self._stage_progress("assets", 1.0), message="Pesi pronti")

            # 3) config esperimento
            exp_name = job["exp_name"]
            exp_dir = os.path.join(job_dir, "logs", exp_name)
            os.makedirs(exp_dir, exist_ok=True)
            self._write_experiment_config(exp_dir, settings)

            python = pipeline.resolve_python(self.paths)
            env = pipeline.build_env(
                self.paths, job_dir, exp_dir, assets_ctx, int(min(8, os.cpu_count() or 2))
            )
            ctx = {
                "python": python,
                "job_dir": job_dir,
                "exp_dir": exp_dir,
                "exp_name": exp_name,
                "raw_dir": raw_dir,
                "settings": settings,
                "pretrained_g": assets_ctx["g"],
                "pretrained_d": assets_ctx["d"],
                "nproc": int(min(8, os.cpu_count() or 2)),
            }

            def run(stage_name: str) -> None:
                if cancel.is_set():
                    raise TrainingError("Annullato", "training_canceled")
                if self._stage_already_done(stage_name, ctx):
                    self._append_log(log_path, "stadio %s: gia' completato, salto" % stage_name)
                    self._update(
                        job_id,
                        progress=self._stage_progress(stage_name, 1.0),
                        message="%s (gia' fatto)" % pipeline.STAGE_LABELS.get(stage_name, stage_name),
                    )
                    return
                self._update(
                    job_id,
                    stage=stage_name,
                    message=pipeline.STAGE_LABELS.get(stage_name, stage_name),
                    progress=self._stage_progress(stage_name, 0.0),
                )
                command = pipeline.build_command(stage_name, ctx)
                self._append_log(log_path, "Comando %s: %s" % (stage_name, " ".join(command)))

                def on_line(line: str) -> None:
                    self._handle_line(job_id, stage_name, line, ctx)

                code = pipeline.run_stage(
                    command,
                    cwd=job_dir,
                    env=env,
                    log_path=log_path,
                    on_line=on_line,
                    cancel_event=cancel,
                    register_process=lambda proc: self._processes.__setitem__(job_id, proc),
                    timeout_s=STAGE_TIMEOUTS.get(stage_name),
                )
                if cancel.is_set():
                    raise TrainingError("Annullato", "training_canceled")
                if code != 0:
                    raise TrainingError(
                        "stadio %s fallito (codice %s): vedi log del job"
                        % (pipeline.STAGE_LABELS.get(stage_name, stage_name), code),
                        "training_stage_failed",
                    )
                self._update(
                    job_id,
                    progress=self._stage_progress(stage_name, 1.0),
                    stages=self._stage_snapshot(job_id, stage_name, "done"),
                )

            run("preprocess")
            if settings["f0"]:
                run("f0")
            run("hubert")

            # filelist (Python puro): richiede le feature HuBERT gia' estratte.
            self._update(job_id, stage="filelist", message="Preparazione liste", progress=self._stage_progress("filelist", 0.0))
            info = build_filelist(
                exp_dir,
                settings["version"],
                bool(settings["f0"]),
                pipeline.MUTE_DIR,
                settings["sample_rate"],
            )
            self._append_log(log_path, "filelist: %d clip (+%d mute)" % (info["entries"], info["mute"]))
            self._update(job_id, progress=self._stage_progress("filelist", 1.0))

            run("train")
            best_model = ""
            if job.get("evaluate_checkpoints", True):
                best_model = self._evaluate_checkpoints(job_id, job, job_dir, log_path)
            run("index")

            # finalize
            self._update(job_id, stage="finalize", message="Salvataggio modello", progress=self._stage_progress("finalize", 0.2))
            previous_output = (self.get_job(job_id) or {}).get("output") or {}
            output = self._finalize(job, job_dir, exp_dir, best_model)
            if previous_output.get("evaluations"):
                output["evaluations"] = previous_output["evaluations"]
                output["best_checkpoint"] = previous_output.get("best_checkpoint", "")
            self._update(
                job_id,
                persist=True,
                status="completed",
                stage="completed",
                progress=100.0,
                message="Modello pronto",
                output=output,
                finished_at=time.time(),
            )
            self._append_log(log_path, "Completato: %s" % output)
        except TrainingError as exc:
            if exc.code == "training_canceled":
                self._update(
                    job_id,
                    persist=True,
                    status="canceled",
                    stage="canceled",
                    message="Annullato",
                    error="",
                    finished_at=time.time(),
                )
            else:
                self._update(
                    job_id,
                    persist=True,
                    status="failed",
                    stage="failed",
                    message=exc.message,
                    error=exc.message,
                    finished_at=time.time(),
                )
            self._append_log(log_path, "ERRORE: %s" % exc.message)
        except Exception as exc:  # pragma: no cover - difensivo
            self._update(
                job_id,
                persist=True,
                status="failed",
                stage="failed",
                message=str(exc),
                error=str(exc),
                finished_at=time.time(),
            )
            self._append_log(log_path, "ERRORE imprevisto: %s" % exc)
        finally:
            self._processes.pop(job_id, None)
            if held_queue and self.job_queue is not None:
                try:
                    self.job_queue.release()
                except Exception:
                    pass

    # --------------------------------------------------------------- utilities
    def _wait_for_idle_queue(self, cancel: threading.Event) -> None:
        if self.job_queue is None:
            return
        deadline = time.time() + 300
        while time.time() < deadline:
            if cancel.is_set():
                raise TrainingError("Annullato", "training_canceled")
            try:
                running = int(self.job_queue.stats().get("running", 0))
            except Exception:
                running = 0
            if running == 0:
                return
            time.sleep(1.0)

    def _write_experiment_config(self, exp_dir: str, settings: Dict[str, Any]) -> None:
        version = settings["version"]
        sample_rate = int(settings["sample_rate"])
        config_version = "v1" if version == "v1" or sample_rate == 40000 else "v2"
        template = os.path.join(pipeline.VENDOR_ROOT, "configs", config_version, "%dk.json" % (sample_rate // 1000))
        if not os.path.isfile(template):
            raise TrainingError("config di training mancante: %s" % template, "training_config_missing")
        with open(template, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        config.setdefault("train", {})["batch_size"] = int(settings["batch_size"])
        target = os.path.join(exp_dir, "config.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=4)
            handle.write("\n")

    def _stage_already_done(self, stage: str, ctx: Dict[str, Any]) -> bool:
        exp_dir = ctx["exp_dir"]
        if stage == "preprocess":
            return _has_files(os.path.join(exp_dir, "0_gt_wavs")) and _has_files(
                os.path.join(exp_dir, "1_16k_wavs")
            )
        if stage == "f0":
            return _has_files(os.path.join(exp_dir, "2a_f0")) and _has_files(
                os.path.join(exp_dir, "2b-f0nsf")
            )
        if stage == "hubert":
            feature = "3_feature256" if ctx["settings"]["version"] == "v1" else "3_feature768"
            return _has_files(os.path.join(exp_dir, feature))
        if stage == "train":
            return _has_files(os.path.join(ctx["job_dir"], "weights"))
        if stage == "index":
            return _has_files(os.path.join(ctx["job_dir"], "output"))
        return False

    def _stage_snapshot(self, job_id: str, stage: str, status: str) -> Dict[str, Any]:
        job = self.get_job(job_id) or {}
        stages = dict(job.get("stages") or {})
        stages[stage] = {"status": status, "at": time.time()}
        return stages

    def _stage_progress(self, stage: str, fraction: float) -> float:
        start, end = STAGE_RANGES.get(stage, (0.0, 100.0))
        return round(start + (end - start) * max(0.0, min(1.0, fraction)), 1)

    def _append_log(self, path: str, message: str) -> None:
        try:
            with open(path, "a", encoding="utf-8", errors="replace") as handle:
                handle.write("%s %s\n" % (time.strftime("%H:%M:%S"), message))
        except OSError:
            pass

    def _handle_line(self, job_id: str, stage: str, line: str, ctx: Dict[str, Any]) -> None:
        settings = ctx["settings"]
        match = pipeline.PROGRESS_RE.search(line)
        if match and stage in ("preprocess", "f0", "hubert"):
            done, total = int(match.group(1)), int(match.group(2))
            fraction = done / total if total else 0.0
            self._update(
                job_id,
                progress=self._stage_progress(stage, fraction),
                message="%s %d/%d" % (pipeline.STAGE_LABELS.get(stage, stage), done, total),
            )
            return
        match = pipeline.EPOCH_RE.search(line)
        if match and stage == "train":
            epoch = int(match.group(1))
            total = int(settings["epochs"]) or 1
            fraction = max(0.0, min(1.0, epoch / total))
            self._update(
                job_id,
                epoch=epoch,
                total_epochs=total,
                progress=self._stage_progress("train", fraction),
                message="Epoca %d/%d" % (epoch, total),
            )
            return
        match = pipeline.STEP_RE.search(line)
        if match and stage == "train":
            epoch = int(match.group(1))
            percent = int(match.group(2))
            self._update(job_id, message="Epoca %d · batch %d%%" % (epoch, percent))
            return
        match = pipeline.LOSS_RE.search(line)
        if match:
            try:
                loss = float(match.group(1))
            except ValueError:
                return
            if loss == loss and loss not in (float("inf"), float("-inf")):
                self._update(job_id, loss=round(loss, 4))

    # --------------------------------------------------------------- finetune
    def _prepare_finetune(
        self, job: Dict[str, Any], job_dir: str, source_model: str, log_path: str
    ) -> str:
        """Converte un .pth esportato nel formato atteso da ``-pg`` e ne fa il backup."""
        if not os.path.isfile(source_model):
            raise TrainingError("modello da rifinire non trovato: %s" % source_model)
        python = pipeline.resolve_python(self.paths)
        base_dir = os.path.join(job_dir, "base")
        os.makedirs(base_dir, exist_ok=True)
        target = os.path.join(base_dir, "G_finetune.pth")
        script = (
            "import sys, torch\n"
            "src, dst = sys.argv[1], sys.argv[2]\n"
            "ckpt = torch.load(src, map_location='cpu')\n"
            "if isinstance(ckpt, dict):\n"
            "    weight = ckpt.get('weight') or ckpt.get('model') or ckpt\n"
            "    config = ckpt.get('config') or []\n"
            "else:\n"
            "    weight, config = ckpt, []\n"
            "torch.save({'model': weight, 'config': config}, dst)\n"
        )
        completed = subprocess.run(
            [python, "-B", "-c", script, source_model, target],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        if completed.returncode != 0 or not os.path.isfile(target):
            raise TrainingError(
                "impossibile preparare il modello da rifinire: %s"
                % ((completed.stderr or "").strip()[-400:] or "errore sconosciuto")
            )
        backups = os.path.join(self.paths.models_dir, "backups")
        os.makedirs(backups, exist_ok=True)
        stem = os.path.splitext(os.path.basename(source_model))[0]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(source_model, os.path.join(backups, "%s_%s.pth" % (stem, stamp)))
        except OSError:
            pass
        self._append_log(log_path, "fine-tune da %s (backup in Modelli/backups)" % stem)
        return target

    # --------------------------------------------------------------- evaluate
    def _eval_sample(self, job: Dict[str, Any]) -> str:
        explicit = str(job.get("test_sample") or "").strip()
        if explicit and os.path.isfile(explicit):
            return explicit
        raw_dir = os.path.join(job["dir"], "dataset", "raw")
        if os.path.isdir(raw_dir):
            for name in sorted(os.listdir(raw_dir)):
                if os.path.splitext(name)[1].lower() in dataset_module.AUDIO_EXTENSIONS:
                    return os.path.join(raw_dir, name)
        return ""

    def _checkpoints(self, job: Dict[str, Any]) -> List[str]:
        weights = os.path.join(job["dir"], "weights")
        if not os.path.isdir(weights):
            return []
        names = [
            name
            for name in os.listdir(weights)
            if name.lower().endswith(".pth")
        ]
        paths = [os.path.join(weights, name) for name in names]
        paths.sort(key=lambda item: os.path.getmtime(item))
        if len(paths) > 8:
            step = max(1, len(paths) // 8)
            paths = paths[::step][:7] + [paths[-1]]
        return paths

    def _evaluate_checkpoints(
        self, job_id: str, job: Dict[str, Any], job_dir: str, log_path: str
    ) -> str:
        """Prova ogni checkpoint su un campione di 10 s e restituisce il migliore."""
        sample = self._eval_sample(job)
        checkpoints = self._checkpoints(job)
        if not sample or len(checkpoints) < 2:
            return ""
        python = pipeline.resolve_python(self.paths)
        helper = os.path.join(self.paths.app_root, "tools", "reaper_helper.py")
        if not os.path.isfile(helper):
            return ""
        results: List[Dict[str, Any]] = []
        best_path = ""
        best_score = -1.0
        total = len(checkpoints)
        for position, checkpoint in enumerate(checkpoints, start=1):
            stem = os.path.splitext(os.path.basename(checkpoint))[0]
            out_dir = os.path.join(job_dir, "eval", stem)
            self._update(
                job_id,
                stage="evaluate",
                progress=self._stage_progress("evaluate", (position - 1) / total),
                message="Test checkpoint %d/%d" % (position, total),
            )
            self._append_log(log_path, "checkpoint: %s" % stem)
            command = [
                python,
                "-B",
                helper,
                "--input",
                sample,
                "--output-dir",
                out_dir,
                "--model",
                checkpoint,
                "--pitch",
                "0",
                "--method",
                "rmvpe",
                "--index-rate",
                "0",
                "--protect",
                "0.33",
            ]
            try:
                from ..tuning.auto_tune import compare

                samples: List[Dict[str, Any]] = []
                # Due passate sullo stesso campione riducono il rumore dell'inferenza.
                for run_index in range(2):
                    run_dir = os.path.join(out_dir, "run%d" % (run_index + 1))
                    run_command = list(command)
                    run_command[run_command.index("--output-dir") + 1] = run_dir
                    completed = subprocess.run(
                        run_command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=600,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                    )
                    payload = None
                    for line in (completed.stdout or "").splitlines():
                        if line.startswith("RESULT "):
                            payload = json.loads(line[len("RESULT "):])
                    if not payload or not payload.get("ok"):
                        raise RuntimeError((payload or {}).get("error") or "conversione fallita")
                    samples.append(compare(sample, payload["output"], 0))
                numeric_keys = ("cost", "score", "f0_rmse_cents", "centroid_ratio", "hf_ratio", "voiced_ratio", "clipping")
                metrics = {}
                for key in numeric_keys:
                    values = [float(item.get(key) or 0.0) for item in samples]
                    metrics[key] = round(sum(values) / len(values), 4)
                entry = {"checkpoint": stem, "path": checkpoint, **metrics, "runs": len(samples)}
                results.append(entry)
                self._append_log(
                    log_path,
                    "checkpoint %s: score=%.1f cost=%.2f" % (stem, metrics["score"], metrics["cost"]),
                )
                if float(metrics["score"]) > best_score:
                    best_score = float(metrics["score"])
                    best_path = checkpoint
            except Exception as exc:  # un checkpoint rotto non blocca gli altri
                results.append({"checkpoint": stem, "path": checkpoint, "error": str(exc)})
                self._append_log(log_path, "checkpoint %s: errore %s" % (stem, exc))
        results.sort(key=lambda item: float(item.get("score") or -1), reverse=True)
        self._update(
            job_id,
            persist=True,
            progress=self._stage_progress("evaluate", 1.0),
            message="Miglior checkpoint: %s" % (os.path.basename(best_path) if best_path else "nessuno"),
            output={"evaluations": results, "best_checkpoint": best_path},
        )
        return best_path

    # ---------------------------------------------------------------- finalize
    def _finalize(self, job: Dict[str, Any], job_dir: str, exp_dir: str, best_model: str = "") -> Dict[str, Any]:
        weights_dir = os.path.join(job_dir, "weights")
        candidates = [
            os.path.join(weights_dir, name)
            for name in os.listdir(weights_dir)
            if name.lower().endswith(".pth")
        ] if os.path.isdir(weights_dir) else []
        if not candidates:
            raise TrainingError("training completato ma nessun .pth prodotto", "training_output_missing")
        model_source = best_model if best_model and os.path.isfile(best_model) else max(candidates, key=os.path.getmtime)

        index_candidates: List[str] = []
        for directory in (os.path.join(job_dir, "output"), exp_dir):
            if os.path.isdir(directory):
                index_candidates.extend(
                    os.path.join(directory, name)
                    for name in os.listdir(directory)
                    if name.lower().startswith("added_") and name.lower().endswith(".index")
                )
        index_source = max(index_candidates, key=os.path.getmtime) if index_candidates else ""

        models_dir = self.paths.models_dir
        os.makedirs(models_dir, exist_ok=True)
        if os.path.isfile(os.path.join(models_dir, job["exp_name"] + ".pth")):
            backup_dir = os.path.join(models_dir, "backups")
            os.makedirs(backup_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(
                os.path.join(models_dir, job["exp_name"] + ".pth"),
                os.path.join(backup_dir, "%s_%s.pth" % (job["exp_name"], stamp)),
            )
            with open(os.path.join(job_dir, "log.txt"), "a", encoding="utf-8", errors="replace") as handle:
                handle.write("%s backup modello precedente in Modelli/backups\n" % time.strftime("%H:%M:%S"))
        stem = job["exp_name"]
        destination = os.path.join(models_dir, stem + ".pth")
        suffix = 2
        while os.path.exists(destination):
            stem = "%s-%d" % (job["exp_name"], suffix)
            destination = os.path.join(models_dir, stem + ".pth")
            suffix += 1
        shutil.copy2(model_source, destination)

        index_destination = ""
        if index_source:
            original = os.path.basename(index_source)
            renamed = original.replace(job["exp_name"], stem)
            index_destination = os.path.join(models_dir, renamed)
            shutil.copy2(index_source, index_destination)

        self._refresh_android_models()
        return {
            "model": destination,
            "index": index_destination,
            "model_name": os.path.basename(destination),
            "exp_dir": exp_dir,
        }

    def _refresh_android_models(self) -> None:
        settings = self.settings_manager.settings
        android = settings.android
        if not (android.enabled and android.shared_dir):
            return
        try:
            from ..android_bridge import scan_entries, shared_paths, write_models_file

            paths = shared_paths(android.shared_dir, android)
            entries = list(scan_entries(self.settings_manager, self.paths).get("models") or [])
            write_models_file(paths["models_path"], entries)
        except Exception:
            return


def _has_files(directory: str) -> bool:
    try:
        return os.path.isdir(directory) and any(True for _ in os.scandir(directory))
    except OSError:
        return False
