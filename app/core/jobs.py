"""Coda dei job di conversione (un solo worker GPU, stati ed eventi SSE)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..events import EventBus
from ..settings import SettingsManager
from .engine import Engine, EngineError, InferParams

LOGGER = logging.getLogger("rvc.jobs")

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELED = "canceled"

TERMINAL_STATES = (DONE, FAILED, CANCELED)
AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".opus", ".wma")


@dataclass
class Job:
    id: str
    input_path: str
    output_path: str
    model_path: str
    index_path: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    source: str = "manual"
    state: str = QUEUED
    stage: str = ""
    progress: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    elapsed_s: float = 0.0
    duration_s: float = 0.0
    sample_rate: int = 0
    error_code: str = ""
    error_message: str = ""
    detail: str = ""
    retries: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["basename"] = os.path.basename(self.input_path)
        data["output_name"] = os.path.basename(self.output_path)
        data["terminal"] = self.state in TERMINAL_STATES
        return data

    @property
    def key(self) -> str:
        raw = "|".join(
            [
                os.path.abspath(self.input_path).lower(),
                _file_signature(self.input_path),
                os.path.abspath(self.model_path).lower() if self.model_path else "",
                os.path.abspath(self.index_path).lower() if self.index_path else "",
                json.dumps(self.params, sort_keys=True),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class JobQueue:
    """Coda FIFO con un worker, cancel cooperativo, retry e persistenza leggera."""

    def __init__(
        self,
        engine: Engine,
        settings_manager: SettingsManager,
        bus: EventBus,
        jobs_state_path: Optional[str] = None,
        max_history: int = 500,
    ):
        self._engine = engine
        self._settings_manager = settings_manager
        self._bus = bus
        self._jobs_state_path = jobs_state_path
        self._max_history = max_history
        self._lock = threading.RLock()
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._cancel_events: Dict[str, threading.Event] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._current: Optional[str] = None
        self._completed_keys: Dict[str, float] = {}
        self._loaded_model: Optional[tuple] = None
        self._load()

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop, name="rvc-job-queue", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=timeout)
        self._engine.shutdown()

    def set_engine(self, engine: Engine) -> None:
        with self._lock:
            self._engine = engine
            self._loaded_model = None

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def current_job_id(self) -> Optional[str]:
        return self._current

    # -------------------------------------------------------------------- api
    def enqueue(
        self,
        input_path: str,
        params: InferParams,
        model_path: str = "",
        index_path: str = "",
        source: str = "manual",
        output_dir: str = "",
        dedupe: bool = True,
        output_path: str = "",
    ) -> Job:
        settings = self._settings_manager.settings
        input_path = os.path.abspath(input_path)
        model_path = os.path.abspath(model_path or settings.audio.model_path)
        index_path = os.path.abspath(index_path or settings.audio.index_path or "")
        if not index_path:
            index_path = ""
        if not os.path.isfile(input_path):
            raise FileNotFoundError(input_path)
        if not model_path or not os.path.isfile(model_path):
            raise FileNotFoundError("modello non trovato: %s" % model_path)

        target_dir = output_dir or settings.audio.output_dir
        if not target_dir:
            raise ValueError("cartella output non configurata")
        os.makedirs(target_dir, exist_ok=True)
        extension = "." + (params.output_format or "wav").lstrip(".")
        stem = os.path.splitext(os.path.basename(input_path))[0]
        android = getattr(settings, "android", None)
        if output_path:
            output_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            _remove_if_exists(output_path)
        elif (
            android is not None
            and android.enabled
            and android.same_name_output
            and source == "monitor"
        ):
            # Compatibilita' Android: AudioOut/<stesso nome dell'input>.
            output_path = os.path.join(target_dir, stem + extension)
            _remove_if_exists(output_path)
            os.makedirs(target_dir, exist_ok=True)
        else:
            output_path = _unique_path(target_dir, stem, extension)

        job = Job(
            id=uuid.uuid4().hex,
            input_path=input_path,
            output_path=output_path,
            model_path=model_path,
            index_path=index_path,
            params=params.to_dict(),
            source=source,
        )

        with self._lock:
            if dedupe:
                done_at = self._completed_keys.get(job.key)
                if done_at and (time.time() - done_at) < 3600:
                    same = self._find_by_key(job.key)
                    if same is not None:
                        LOGGER.info(
                            "job duplicato ignorato: %s", os.path.basename(input_path)
                        )
                        return same
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._cancel_events[job.id] = threading.Event()
            self._trim()
        self._persist(job)
        self._publish(job)
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50, include_terminal: bool = True) -> List[Job]:
        with self._lock:
            ids = list(self._order)
        jobs = []
        for job_id in reversed(ids):
            job = self.get(job_id)
            if job is None:
                continue
            if not include_terminal and job.state in TERMINAL_STATES:
                continue
            jobs.append(job)
            if len(jobs) >= max(1, limit):
                break
        return jobs

    def stats(self) -> Dict[str, int]:
        with self._lock:
            jobs = list(self._jobs.values())
        result = {QUEUED: 0, RUNNING: 0, DONE: 0, FAILED: 0, CANCELED: 0}
        for job in jobs:
            result[job.state] = result.get(job.state, 0) + 1
        result["total"] = len(jobs)
        result["pending"] = result[QUEUED] + result[RUNNING]
        return result

    def cancel(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            event = self._cancel_events.get(job_id)
            if job.state == QUEUED:
                if event:
                    event.set()
                job.state = CANCELED
                job.finished_at = time.time()
                job.error_code = "canceled"
                job.error_message = "Job annullato prima dell'esecuzione"
            elif job.state == RUNNING:
                if event:
                    event.set()
                try:
                    self._engine.cancel()
                except Exception:
                    LOGGER.exception("errore durante la cancel del motore")
        self._persist(job)
        self._publish(job)
        return job

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.state == RUNNING:
                self.cancel(job_id)
                return False
            self._jobs.pop(job_id, None)
            self._cancel_events.pop(job_id, None)
            if job_id in self._order:
                self._order.remove(job_id)
        return True

    def clear_finished(self) -> int:
        with self._lock:
            removable = [
                job_id
                for job_id, job in self._jobs.items()
                if job.state in TERMINAL_STATES
            ]
            for job_id in removable:
                self._jobs.pop(job_id, None)
                self._cancel_events.pop(job_id, None)
                if job_id in self._order:
                    self._order.remove(job_id)
        return len(removable)

    def output_path_for(self, job: Job) -> str:
        return job.output_path

    # ---------------------------------------------------------------- internals
    def _worker_loop(self) -> None:
        LOGGER.info("job queue avviata")
        while self._running:
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job_id is None:
                break
            job = self.get(job_id)
            if job is None or job.state != QUEUED:
                continue
            if self._cancel_events[job_id].is_set():
                job.state = CANCELED
                job.finished_at = time.time()
                self._persist(job)
                self._publish(job)
                continue
            self._run_job(job)
        LOGGER.info("job queue terminata")

    def _run_job(self, job: Job) -> None:
        event = self._cancel_events.setdefault(job.id, threading.Event())
        with self._lock:
            job.state = RUNNING
            job.started_at = time.time()
            job.stage = "loading"
            job.progress = 0.0
            self._current = job.id
        self._publish(job)

        def on_log(message: str) -> None:
            LOGGER.info("[job %s] %s", job.id[:8], message)
            self._bus.publish(
                "job_log",
                {"job_id": job.id, "message": str(message)},
            )

        def on_stage(stage: str, progress: Optional[float]) -> None:
            job.stage = stage
            if progress is not None:
                job.progress = float(progress)
            self._publish(job)

        try:
            self._ensure_model(job)
            if event.is_set():
                raise EngineError("canceled", "Job annullato")
            result = self._engine.infer(
                job.input_path,
                job.output_path,
                InferParams(**job.params),
                on_log=on_log,
                on_stage=on_stage,
                is_cancelled=event.is_set,
            )
        except EngineError as exc:
            self._finish_error(job, exc.code, exc.message, exc.detail)
            return
        except Exception as exc:  # pragma: no cover - difensivo
            LOGGER.exception("errore inatteso nel job %s", job.id)
            self._finish_error(job, "engine_error", str(exc), "")
            return
        finally:
            with self._lock:
                self._current = None

        if event.is_set() or (not result.ok and result.error_code == "canceled"):
            job.state = CANCELED
            job.error_code = "canceled"
            job.error_message = "Job annullato"
        elif result.ok:
            job.state = DONE
            job.output_path = result.output_path or job.output_path
            job.duration_s = result.duration_s
            job.sample_rate = result.sample_rate
            job.elapsed_s = result.elapsed_s
            job.progress = 100.0
            job.stage = "done"
            with self._lock:
                self._completed_keys[job.key] = time.time()
        else:
            self._finish_error(job, result.error_code, result.error_message, result.detail)

        job.finished_at = time.time()
        job.elapsed_s = job.elapsed_s or (job.finished_at - (job.started_at or job.created_at))
        self._persist(job)
        self._publish(job)

    def _finish_error(self, job: Job, code: str, message: str, detail: str) -> None:
        if job.retries < 1 and code in ("engine_crashed", "worker_error"):
            job.retries += 1
            job.state = QUEUED
            job.error_code = ""
            job.error_message = ""
            job.detail = ""
            job.stage = "retry"
            self._persist(job)
            self._publish(job)
            self._queue.put(job.id)
            return
        job.state = FAILED
        job.error_code = code or "engine_error"
        job.error_message = message or "errore sconosciuto"
        job.detail = detail or ""
        job.finished_at = time.time()

    def _ensure_model(self, job: Job) -> None:
        signature = (
            os.path.abspath(job.model_path),
            os.path.abspath(job.index_path) if job.index_path else "",
            str(job.params.get("model_version", "v2")),
        )
        settings = self._settings_manager.settings
        if self._loaded_model == signature:
            return
        job.stage = "loading"
        self._publish(job)
        self._engine.load(
            job.model_path,
            job.index_path,
            version=str(job.params.get("model_version", "v2")),
            device=settings.engine.device,
        )
        self._loaded_model = signature

    # ------------------------------------------------------------- persistence
    def _publish(self, job: Job) -> None:
        self._bus.publish("job", job.to_dict())

    def _persist(self, job: Job) -> None:
        if not self._jobs_state_path:
            return
        try:
            os.makedirs(os.path.dirname(self._jobs_state_path), exist_ok=True)
            with open(self._jobs_state_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(job.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            LOGGER.exception("impossibile persistere il job %s", job.id)

    def _load(self) -> None:
        if not self._jobs_state_path or not os.path.isfile(self._jobs_state_path):
            return
        try:
            with open(self._jobs_state_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()[-self._max_history :]
        except OSError:
            return
        latest: Dict[str, Job] = {}
        for line in lines:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            job_id = data.get("id")
            if not job_id:
                continue
            latest[job_id] = Job(
                id=job_id,
                input_path=data.get("input_path", ""),
                output_path=data.get("output_path", ""),
                model_path=data.get("model_path", ""),
                index_path=data.get("index_path", ""),
                params=data.get("params") or {},
                source=data.get("source", "manual"),
                state=data.get("state", FAILED),
                stage=data.get("stage", ""),
                progress=data.get("progress"),
                created_at=float(data.get("created_at", time.time())),
                started_at=data.get("started_at"),
                finished_at=data.get("finished_at"),
                elapsed_s=float(data.get("elapsed_s", 0.0)),
                duration_s=float(data.get("duration_s", 0.0)),
                sample_rate=int(data.get("sample_rate", 0) or 0),
                error_code=data.get("error_code", ""),
                error_message=data.get("error_message", ""),
                detail=data.get("detail", ""),
                retries=int(data.get("retries", 0) or 0),
            )
        with self._lock:
            for job in latest.values():
                if job.state in (RUNNING, QUEUED):
                    job.state = FAILED
                    job.error_code = "interrupted"
                    job.error_message = "Job interrotto dal riavvio"
                self._jobs[job.id] = job
            self._order = sorted(
                self._jobs.keys(), key=lambda jid: self._jobs[jid].created_at
            )

    def _trim(self) -> None:
        if len(self._order) <= self._max_history:
            return
        overflow = len(self._order) - self._max_history
        for job_id in self._order[:overflow]:
            job = self._jobs.get(job_id)
            if job and job.state not in TERMINAL_STATES:
                break
            self._jobs.pop(job_id, None)
            self._cancel_events.pop(job_id, None)
        self._order = self._order[overflow:]

    def _find_by_key(self, key: str) -> Optional[Job]:
        for job in self._jobs.values():
            if job.state == DONE and job.key == key:
                return job
        return None


def _unique_path(directory: str, stem: str, extension: str) -> str:
    candidate = os.path.join(directory, "%s%s" % (stem, extension))
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, "%s (%d)%s" % (stem, index, extension))
        index += 1
    return candidate


def _file_signature(path: str) -> str:
    """Firma leggera del file di input: permette di riconvertire un nome riusato."""
    try:
        stat = os.stat(path)
    except OSError:
        return ""
    return "%d:%d" % (stat.st_size, int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))))


def _remove_if_exists(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
