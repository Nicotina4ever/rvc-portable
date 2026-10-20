"""Motore RVC reale: adapter Python verso il worker persistente.

Il backend **non importa torch**: ``RvcEngine`` avvia ``app/core/worker.py``
con l'interprete del runtime del motore e gli parla via JSONL su
stdin/stdout (protocollo documentato in ``app/core/worker.py``).

Responsabilita' di questo modulo:

- risoluzione del device richiesto (``auto`` -> cuda/mps/cpu) **senza torch**,
  tramite il probe del runtime gia' usato dalla Diagnostica;
- ``CUDA_VISIBLE_DEVICES`` impostata nell'ambiente del worker **prima**
  dell'import di torch (per ``cuda:N`` il worker vede solo ``cuda:0``);
- spawn con ``CREATE_NO_WINDOW`` su Windows, ``cwd = app_root``, timeout di
  avvio, riavvio automatico con backoff se il worker termina;
- modello caldo: ``load`` e' un no-op se modello/indice/versione/device non
  cambiano; il worker viene scaricato su cambio modello e, se configurato,
  dopo ``idle_unload_minutes`` di inattivita' o a fine job con
  ``warm_model = false``;
- stderr del worker riversato nel log del backend (ultime righe conservate
  per diagnosticare i crash);
- stage/log inoltrati ai callback del job (``on_stage``/``on_log``) e cancel
  cooperativo inoltrato al worker.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..security import subprocess_no_window
from . import devices
from .engine import Engine, EngineError, EngineStatus, InferParams, InferResult
from .index_shim import resolved_index_path

LOGGER = logging.getLogger("rvc.engine")

START_TIMEOUT_S = 60.0
PING_TIMEOUT_S = 30.0
LOAD_TIMEOUT_S = 900.0
INFER_TIMEOUT_S = 1800.0
UNLOAD_TIMEOUT_S = 60.0
STOP_TIMEOUT_S = 10.0
CANCEL_GRACE_S = 180.0
BASEMODEL_MIN_BYTES = 100 * 1024 * 1024
MAX_CRASHES = 4
CRASH_WINDOW_S = 300.0
IDLE_TICK_S = 15.0


class RvcEngine(Engine):
    """Motore RVC reale delegato a un processo worker persistente."""

    name = "rvc"

    def __init__(
        self,
        paths,
        settings_manager=None,
        python_executable: Optional[str] = None,
        worker_command: Optional[List[str]] = None,
        worker_module: str = "app.core.worker",
    ):
        self.paths = paths
        self.settings_manager = settings_manager
        self.python_executable = python_executable or paths.runtime_python or sys.executable
        self._worker_command = list(worker_command) if worker_command else None
        self._worker_module = worker_module

        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._stdin = None
        self._events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_tail: "deque[str]" = deque(maxlen=60)
        self._request_id = 0

        self._runtime = _inspect_runtime(self.python_executable)
        self._requested_device = "auto"
        self._effective_device = ""
        self._device_warnings: List[str] = []
        self._worker_key: Optional[Tuple[str, Optional[str]]] = None
        self._worker_device = ""
        self._desired: Optional[Dict[str, Any]] = None
        self._loaded_sig: Optional[tuple] = None
        self._loaded = False
        self._busy = False
        self._cancel_sent = False
        self._last_activity = time.time()
        self._crash_count = 0
        self._last_crash_at = 0.0
        self._probe: Optional[devices.RuntimeProbe] = None
        self._probe_lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._idle_thread = threading.Thread(
            target=self._idle_loop, name="rvc-engine-idle", daemon=True
        )

        if self._runtime["engine_ok"]:
            self._idle_thread.start()
            threading.Thread(
                target=self._probe_async, name="rvc-engine-probe", daemon=True
            ).start()

    # ------------------------------------------------------------------ status
    def status(self) -> EngineStatus:
        runtime = self._runtime
        available = bool(runtime["engine_ok"] and runtime["base_models_ok"])
        code = ""
        message = ""
        if not available:
            if not runtime["python_exists"]:
                code = "engine_unavailable"
                message = "Runtime del motore non trovato: %s" % self.python_executable
            elif not runtime["engine_ok"]:
                code = "engine_unavailable"
                message = (
                    "rvc-python non trovato nel runtime del motore: "
                    "ripristina runtime/ con tools/bootstrap.py"
                )
            else:
                code = "engine_unavailable"
                message = (
                    "Pesi base mancanti o troncati in %s: ripristina il runtime"
                    % (runtime["base_models_dir"] or "runtime")
                )
        with self._lock:
            probe = self._probe
            extra: Dict[str, Any] = {
                "engine_python": self.python_executable,
                "worker_running": self._proc is not None and self._proc.poll() is None,
                "worker_device": self._worker_device,
                "base_models_ok": runtime["base_models_ok"],
            }
            if self._device_warnings:
                extra["warnings"] = list(self._device_warnings)
            if probe is not None:
                extra.update(
                    {
                        "python": probe.python_version,
                        "torch": probe.torch,
                        "cuda": probe.cuda,
                        "mps": probe.mps,
                        "gpu_name": probe.gpu_name,
                        "vram_gb": probe.vram_gb,
                        "engine_ok": probe.engine_ok,
                        "fairseq_ok": probe.fairseq_ok,
                    }
                )
            return EngineStatus(
                available=available,
                code=code,
                message=message,
                device=self._effective_device or self._requested_device,
                requested_device=self._requested_device,
                model_path=(self._desired or {}).get("model", ""),
                index_path=(self._desired or {}).get("index", ""),
                model_version=(self._desired or {}).get("version", "v2"),
                loaded=self._loaded,
                warm=self._loaded,
                busy=self._busy,
                extra=extra,
            )

    # -------------------------------------------------------------------- load
    def load(
        self,
        model_path: str,
        index_path: str = "",
        version: str = "v2",
        device: str = "auto",
    ) -> None:
        if not self._runtime["engine_ok"]:
            raise EngineError(
                "engine_unavailable", self.status().message or "motore non disponibile"
            )
        model = os.path.abspath(os.path.expanduser(str(model_path or "").strip().strip('"')))
        if not model or not os.path.isfile(model):
            raise EngineError("model_invalid", "modello non trovato: %s" % model)
        version = str(version or "v2").strip().lower()
        if version not in ("v1", "v2"):
            version = "v2"
        index = str(index_path or "").strip().strip('"')
        resolved_index = ""
        if index:
            resolved_index = resolved_index_path(index, self.paths.cache_dir)
            if not os.path.isfile(resolved_index):
                raise EngineError("index_invalid", "indice non trovato: %s" % index)

        requested = _normalize_requested_device(
            device or self._settings_value("device", "auto")
        )
        effective, worker_device, visible, warnings = self._plan_device(requested)
        desired = {
            "model": model,
            "index": resolved_index,
            "version": version,
            "requested_device": requested,
            "effective_device": effective,
            "worker_device": worker_device,
            "visible": visible,
        }
        signature = (model, resolved_index, version, worker_device, visible)

        with self._lock:
            self._desired = desired
            self._requested_device = requested
            self._effective_device = effective
            self._device_warnings = list(warnings)
            worker_alive = self._proc is not None and self._proc.poll() is None
            if (
                self._loaded
                and worker_alive
                and self._worker_key == (worker_device, visible)
                and self._loaded_sig == signature
            ):
                self._last_activity = time.time()
                return
            if worker_alive and self._worker_key != (worker_device, visible):
                LOGGER.info(
                    "device del motore cambiato (%s -> %s): riavvio del worker",
                    self._worker_key,
                    (worker_device, visible),
                )
                self._stop_worker(graceful=True)
            self._ensure_worker(worker_device, visible, reload=False)
            self._desired = desired
            data = self._load_on_worker(desired)
            self._apply_status_data(data)
            self._loaded_sig = signature
            self._last_activity = time.time()

    def _load_on_worker(self, desired: Dict[str, Any]) -> Dict[str, Any]:
        request = {
            "op": "load",
            "model": desired["model"],
            "index": desired["index"],
            "version": desired["version"],
            "device": desired["worker_device"],
        }
        request_id = self._send(request)
        response = self._wait_control(request_id, LOAD_TIMEOUT_S, context="load")
        if response.get("ev") == "error":
            code = str(response.get("code") or "engine_error")
            raise EngineError(
                code,
                str(response.get("message") or "caricamento modello fallito"),
                str(response.get("detail") or ""),
            )
        data = response.get("data") or {}
        self._loaded = True
        self._loaded_sig = (
            desired.get("model", ""),
            desired.get("index", ""),
            desired.get("version", "v2"),
            desired.get("worker_device", ""),
            desired.get("visible"),
        )
        self._crash_count = 0
        return data

    def _apply_status_data(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        reported = str(data.get("device") or "")
        if reported:
            self._worker_device = reported
        if self._effective_device and reported and reported != self._effective_device:
            if self._effective_device.startswith("cuda") and not reported.startswith("cuda"):
                LOGGER.warning(
                    "il worker ha ripiegato su %s (richiesto %s)",
                    reported,
                    self._effective_device,
                )
                self._device_warnings.append(
                    "device richiesto non disponibile: uso %s" % reported
                )
                self._effective_device = reported

    # ------------------------------------------------------------------- infer
    def infer(
        self,
        input_path: str,
        output_path: str,
        params: InferParams,
        on_log: Optional[Callable[[str], None]] = None,
        on_stage: Optional[Callable[[str, Optional[float]], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> InferResult:
        source = os.path.abspath(os.path.expanduser(str(input_path or "").strip().strip('"')))
        if not source or not os.path.isfile(source):
            raise EngineError("input_missing", "file di input non trovato: %s" % source)
        destination = os.path.abspath(os.path.expanduser(str(output_path or "").strip().strip('"')))
        if not destination:
            raise EngineError("validation_error", "percorso di output mancante")

        with self._lock:
            desired = self._desired
            if desired is None:
                raise EngineError(
                    "engine_unavailable", "nessun modello caricato: chiama load() prima di infer()"
                )
            self._ensure_worker(
                desired["worker_device"], desired.get("visible"), reload=True
            )
            self._cancel_sent = False
            self._busy = True
        self._last_activity = time.time()
        self._emit_stage(on_stage, "loading", 0.0)
        try:
            request_id = self._send(
                {
                    "op": "infer",
                    "input": source,
                    "output": destination,
                    "params": params.to_dict(),
                }
            )
            result = self._await_infer(
                request_id, on_log, on_stage, is_cancelled, INFER_TIMEOUT_S
            )
            if result.ok and not self._warm_model():
                try:
                    self.unload()
                except Exception:  # pragma: no cover - best effort
                    LOGGER.debug("unload post-job fallito", exc_info=True)
            return result
        finally:
            with self._lock:
                self._busy = False
            self._last_activity = time.time()

    def _await_infer(
        self,
        request_id: int,
        on_log: Optional[Callable[[str], None]],
        on_stage: Optional[Callable[[str, Optional[float]], None]],
        is_cancelled: Optional[Callable[[], bool]],
        timeout: float,
    ) -> InferResult:
        deadline = time.time() + timeout
        while True:
            if is_cancelled is not None:
                try:
                    cancelled = bool(is_cancelled())
                except Exception:  # pragma: no cover
                    cancelled = False
                if cancelled and not self._cancel_sent:
                    self._cancel_worker()
            remaining = deadline - time.time()
            if remaining <= 0:
                LOGGER.error("timeout inferenza (%.0fs): termino il worker", timeout)
                self._stop_worker(graceful=False)
                raise EngineError(
                    "engine_error",
                    "timeout dell'inferenza (%.0f s)" % timeout,
                    self._stderr_text(),
                )
            try:
                event = self._events.get(timeout=min(0.2, max(0.01, remaining)))
            except queue.Empty:
                continue
            kind = event.get("ev")
            if kind == "__eof__":
                raise EngineError(
                    "engine_crashed",
                    "il worker RVC si e' chiuso durante l'inferenza",
                    self._stderr_text(),
                )
            if event.get("id") != request_id:
                self._forward_async(event, on_log, on_stage)
                continue
            if kind == "stage":
                self._forward_async(event, on_log, on_stage)
                continue
            if kind == "log":
                self._forward_async(event, on_log, on_stage)
                continue
            if kind == "done":
                return InferResult(
                    ok=True,
                    output_path=str(event.get("output") or ""),
                    duration_s=float(event.get("duration_s") or 0.0),
                    sample_rate=int(event.get("sample_rate") or 0),
                    elapsed_s=float(event.get("elapsed_s") or 0.0),
                )
            if kind == "error":
                code = str(event.get("code") or "engine_error")
                if code == "engine_crashed":
                    code = "engine_crashed"
                return InferResult(
                    ok=False,
                    error_code=code,
                    error_message=str(event.get("message") or "errore del motore"),
                    detail=str(event.get("detail") or ""),
                    elapsed_s=float(time.time() - self._last_activity),
                )
            if kind == "result":
                # risposta di controllo inattesa: ignora
                continue

    def cancel(self) -> None:
        self._cancel_worker()

    def _cancel_worker(self) -> None:
        with self._lock:
            if self._cancel_sent:
                return
            self._cancel_sent = True
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return
            try:
                self._send({"op": "cancel"})
            except EngineError:  # pragma: no cover - worker morto
                pass

    # ------------------------------------------------------------------ unload
    def unload(self) -> None:
        with self._lock:
            self._loaded = False
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._desired_clear_loaded()
                return
            try:
                request_id = self._send({"op": "unload"})
                self._wait_control(request_id, UNLOAD_TIMEOUT_S, context="unload")
            except EngineError as exc:
                LOGGER.warning("unload del worker fallito: %s", exc)
                self._stop_worker(graceful=False)
            finally:
                self._desired_clear_loaded()

    def _desired_clear_loaded(self) -> None:
        if self._desired is not None:
            # modello "desiderato" conservato per un eventuale respawn, ma
            # non risulta piu' caldo finche' non viene ricaricato.
            self._loaded = False
            self._loaded_sig = None

    # ---------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        self._shutdown_event.set()
        self._stop_worker(graceful=True)
        self._loaded = False

    # ---------------------------------------------------------------- internals
    def _settings_value(self, name: str, default: Any) -> Any:
        try:
            return getattr(self.settings_manager.settings.engine, name)
        except Exception:
            return default

    def _warm_model(self) -> bool:
        return bool(self._settings_value("warm_model", True))

    def _idle_minutes(self) -> int:
        try:
            return max(0, int(self._settings_value("idle_unload_minutes", 15)))
        except (TypeError, ValueError):
            return 15

    def _idle_loop(self) -> None:
        while not self._shutdown_event.wait(IDLE_TICK_S):
            try:
                with self._lock:
                    if not self._loaded or self._busy or self._proc is None:
                        continue
                    minutes = self._idle_minutes()
                    if minutes <= 0:
                        continue
                    idle_s = time.time() - self._last_activity
                    if idle_s >= minutes * 60:
                        LOGGER.info(
                            "modello inattivo da %.0fs: unload (idle_unload_minutes=%d)",
                            idle_s,
                            minutes,
                        )
                        try:
                            request_id = self._send({"op": "unload"})
                            self._wait_control(request_id, UNLOAD_TIMEOUT_S, context="idle-unload")
                        except EngineError:
                            self._stop_worker(graceful=False)
                        self._loaded = False
            except Exception:  # pragma: no cover - il thread non deve morire
                LOGGER.exception("errore nel monitor di inattivita' del motore")

    def _probe_async(self) -> None:
        try:
            self._probe_now(force=False)
        except Exception:  # pragma: no cover
            LOGGER.debug("probe asincrono del motore fallito", exc_info=True)

    def _probe_now(self, force: bool = False) -> devices.RuntimeProbe:
        with self._probe_lock:
            if self._probe is not None and not force:
                return self._probe
            probe = devices.probe_engine(self.paths, force=force)
            self._probe = probe
            return probe

    def _plan_device(
        self, requested: str
    ) -> Tuple[str, str, Optional[str], List[str]]:
        """Risolve device fisico, device logico del worker e CUDA visibili."""
        probe = self._probe
        if probe is None:
            probe = self._probe_now(force=False)
        effective, warnings = devices.effective_device(requested, probe)
        effective = _normalize_effective_device(effective)
        warnings = list(warnings or [])
        visible: Optional[str] = None
        if effective.startswith("cuda"):
            index = 0
            if ":" in effective:
                try:
                    index = int(effective.split(":", 1)[1])
                except (TypeError, ValueError):
                    index = 0
            visible = str(max(0, index))
            worker_device = "cuda:0"
        elif effective == "mps":
            worker_device = "mps"
        else:
            worker_device = "cpu"
            visible = ""
        if requested == "cpu" and probe.cuda:
            warnings.append(
                "forzo CPU: CUDA disabilitata nel worker tramite CUDA_VISIBLE_DEVICES"
            )
        return effective, worker_device, visible, warnings

    # ------------------------------------------------------------------ worker
    def _ensure_worker(
        self, worker_device: str, visible: Optional[str], reload: bool
    ) -> None:
        key = (worker_device, visible)
        with self._lock:
            proc = self._proc
            if proc is not None and proc.poll() is None and self._worker_key == key:
                desired = self._desired
                if reload and desired is not None and not self._loaded:
                    # Modello scaricato (idle/warm_model=false): ricaricalo
                    # prima di usare il worker.
                    data = self._load_on_worker(desired)
                    self._apply_status_data(data)
                return
            crashed = self._handle_crash_locked(proc)
            if self._crash_count >= MAX_CRASHES:
                raise EngineError(
                    "engine_unavailable",
                    "il worker del motore continua a terminare in modo anomalo",
                    self._stderr_text(),
                )
            if crashed and self._crash_count > 1:
                delay = min(0.25 * (2 ** (self._crash_count - 1)), 4.0)
                LOGGER.warning(
                    "riavvio del worker tra %.2fs (crash #%d)", delay, self._crash_count
                )
                time.sleep(delay)
            self._spawn_worker(worker_device, visible)
            self._worker_key = key
            desired = self._desired
            if reload and desired is not None:
                try:
                    data = self._load_on_worker(desired)
                except EngineError as exc:
                    self._stop_worker(graceful=False)
                    raise EngineError(
                        "engine_crashed",
                        "worker riavviato ma ricaricamento del modello fallito: %s"
                        % exc.message,
                        exc.detail,
                    ) from exc
                self._apply_status_data(data)
            self._crash_count = 0

    def _handle_crash_locked(self, proc: Optional[subprocess.Popen]) -> bool:
        if proc is None:
            return False
        if proc.poll() is None:
            return False
        LOGGER.warning("worker terminato con codice %s", proc.returncode)
        now = time.time()
        if now - self._last_crash_at > CRASH_WINDOW_S:
            self._crash_count = 0
        self._crash_count += 1
        self._last_crash_at = now
        self._loaded = False
        self._dispose_worker(proc)
        return True

    def _spawn_worker(self, worker_device: str, visible: Optional[str]) -> None:
        self._dispose_worker(self._proc)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        existing = env.get("PYTHONPATH") or ""
        env["PYTHONPATH"] = (
            self.paths.app_root
            if not existing
            else self.paths.app_root + os.pathsep + existing
        )
        if visible is None or visible == "":
            env["CUDA_VISIBLE_DEVICES"] = ""
            if worker_device == "mps":
                env.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            env["CUDA_VISIBLE_DEVICES"] = str(visible)

        command = self._worker_command or [
            self.python_executable,
            "-B",
            "-m",
            self._worker_module,
        ]
        command = list(command) + ["--device", worker_device]
        LOGGER.info(
            "avvio worker RVC: device=%s CUDA_VISIBLE_DEVICES=%r",
            worker_device,
            env.get("CUDA_VISIBLE_DEVICES"),
        )
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.paths.app_root,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **subprocess_no_window(),
            )
        except OSError as exc:
            raise EngineError(
                "engine_unavailable", "impossibile avviare il worker RVC: %s" % exc
            ) from exc
        self._proc = proc
        self._stdin = proc.stdin
        self._events = queue.Queue()
        events = self._events
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            args=(proc, events),
            name="rvc-engine-reader",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop,
            args=(proc,),
            name="rvc-engine-stderr",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread.start()

        request_id = self._send({"op": "ping"})
        response = self._wait_control(request_id, PING_TIMEOUT_S, context="startup")
        if response.get("ev") != "result":
            self._dispose_worker(proc)
            raise EngineError(
                "engine_crashed",
                "worker RVC non risponde all'avvio",
                self._stderr_text(),
            )
        data = response.get("data") or {}
        self._worker_device = str(data.get("device") or worker_device)
        LOGGER.info("worker RVC pronto (pid=%s, device=%s)", proc.pid, self._worker_device)

    def _reader_loop(self, proc: subprocess.Popen, events: "queue.Queue[Dict[str, Any]]") -> None:
        stream = proc.stdout
        if stream is None:  # pragma: no cover
            events.put({"ev": "__eof__"})
            return
        try:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    LOGGER.debug("worker stdout non JSON: %s", line[:300])
                    continue
                if isinstance(payload, dict):
                    events.put(payload)
        except (OSError, ValueError):  # pragma: no cover - pipe chiusa
            pass
        finally:
            events.put({"ev": "__eof__"})

    def _stderr_loop(self, proc: subprocess.Popen) -> None:
        stream = proc.stderr
        if stream is None:  # pragma: no cover
            return
        try:
            for line in stream:
                line = line.rstrip()
                if not line:
                    continue
                self._stderr_tail.append(line)
                LOGGER.info("[worker] %s", line)
        except (OSError, ValueError):  # pragma: no cover
            pass

    def _send(self, payload: Dict[str, Any]) -> int:
        with self._lock:
            stdin = self._stdin
            proc = self._proc
            if stdin is None or proc is None or proc.poll() is not None:
                raise EngineError(
                    "engine_crashed",
                    "worker RVC non attivo",
                    self._stderr_text(),
                )
            self._request_id += 1
            request_id = self._request_id
            message = dict(payload)
            message["id"] = request_id
            line = json.dumps(message, ensure_ascii=False)
            try:
                stdin.write(line + "\n")
                stdin.flush()
            except (OSError, ValueError) as exc:
                raise EngineError(
                    "engine_crashed", "scrittura verso il worker fallita: %s" % exc
                ) from exc
            return request_id

    def _wait_control(
        self,
        request_id: int,
        timeout: float,
        context: str = "",
        on_log: Optional[Callable[[str], None]] = None,
        on_stage: Optional[Callable[[str, Optional[float]], None]] = None,
    ) -> Dict[str, Any]:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise EngineError(
                    "engine_error",
                    "timeout del worker RVC durante '%s' (%.0fs)" % (context, timeout),
                    self._stderr_text(),
                )
            try:
                event = self._events.get(timeout=min(0.25, max(0.01, remaining)))
            except queue.Empty:
                if self._proc is not None and self._proc.poll() is not None:
                    raise EngineError(
                        "engine_crashed",
                        "worker RVC terminato durante '%s' (codice %s)"
                        % (context, self._proc.returncode),
                        self._stderr_text(),
                    ) from None
                continue
            kind = event.get("ev")
            if kind == "__eof__":
                raise EngineError(
                    "engine_crashed",
                    "worker RVC terminato durante '%s'" % context,
                    self._stderr_text(),
                )
            if event.get("id") != request_id:
                self._forward_async(event, on_log, on_stage)
                continue
            return event

    def _forward_async(
        self,
        event: Dict[str, Any],
        on_log: Optional[Callable[[str], None]],
        on_stage: Optional[Callable[[str, Optional[float]], None]],
    ) -> None:
        kind = event.get("ev")
        if kind == "log":
            message = str(event.get("message") or "")
            if message:
                LOGGER.info("[worker] %s", message)
                if callable(on_log):
                    try:
                        on_log(message)
                    except Exception:  # pragma: no cover
                        LOGGER.exception("callback on_log fallita")
        elif kind == "stage":
            self._emit_stage(
                on_stage, str(event.get("name") or ""), event.get("pct")
            )

    @staticmethod
    def _emit_stage(
        callback: Optional[Callable[[str, Optional[float]], None]],
        name: str,
        pct: Any,
    ) -> None:
        if not callable(callback) or not name:
            return
        value: Optional[float] = None
        try:
            if pct is not None:
                value = float(pct)
        except (TypeError, ValueError):
            value = None
        try:
            callback(name, value)
        except Exception:  # pragma: no cover
            LOGGER.exception("callback on_stage fallita")

    def _stop_worker(self, graceful: bool) -> None:
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            if graceful and proc.poll() is None:
                try:
                    request_id = self._send({"op": "shutdown"})
                    self._wait_control(request_id, STOP_TIMEOUT_S, context="shutdown")
                except Exception:  # pragma: no cover - best effort
                    LOGGER.debug("shutdown del worker non confermato", exc_info=True)
            self._dispose_worker(proc)

    def _dispose_worker(self, proc: Optional[subprocess.Popen]) -> None:
        if proc is None:
            self._proc = None
            self._stdin = None
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:  # pragma: no cover
                        LOGGER.error("worker RVC non terminato (pid=%s)", proc.pid)
            for thread in (self._reader_thread, self._stderr_thread):
                if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                    thread.join(timeout=5.0)
        finally:
            self._proc = None
            self._stdin = None
            self._reader_thread = None
            self._stderr_thread = None
            self._loaded = False
            self._loaded_sig = None

    def _stderr_text(self) -> str:
        lines = list(self._stderr_tail)[-25:]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_engine(paths, settings_manager=None) -> Engine:
    """Factory usata dal launcher: RvcEngine se il runtime esiste, altrimenti Null."""
    from .engine import NullEngine

    python = paths.runtime_python
    if not (python and os.path.isfile(python)):
        return NullEngine(
            "Runtime del motore non trovato: usa tools/bootstrap.py o ripristina il runtime."
        )
    return RvcEngine(paths, settings_manager=settings_manager)


# ---------------------------------------------------------------------------
# Helper puri (testabili senza torch)
# ---------------------------------------------------------------------------


def _normalize_requested_device(device: Any) -> str:
    value = str(device or "auto").strip().lower()
    if value in ("", "auto"):
        return "auto"
    if value.startswith("dml"):
        return "cpu"
    if value in ("cuda", "cuda:"):
        return "cuda:0"
    if value == "cpu:":
        return "cpu"
    if value.startswith("cuda:"):
        return value
    if value == "mps":
        return "mps"
    return "cpu"


def _normalize_effective_device(device: Any) -> str:
    """Normalizza il risultato del probe; mai DirectML."""
    value = str(device or "cpu").strip().lower()
    if value.startswith("dml"):
        return "cpu"
    if value in ("cuda", "cuda:"):
        return "cuda:0"
    if value == "cpu:":
        return "cpu"
    return value or "cpu"


def _inspect_runtime(python_executable: str) -> Dict[str, Any]:
    """Ispezione leggera del runtime (niente subprocess, niente torch)."""
    info: Dict[str, Any] = {
        "python_exists": bool(python_executable and os.path.isfile(python_executable)),
        "engine_ok": False,
        "base_models_ok": False,
        "base_models_dir": "",
        "missing_base_models": [],
    }
    if not info["python_exists"]:
        return info
    root = os.path.dirname(os.path.abspath(python_executable))
    candidates = [
        os.path.join(root, "Lib", "site-packages"),
        os.path.join(root, "lib", "site-packages"),
    ]
    try:
        candidates.extend(sorted(glob.glob(os.path.join(root, "lib", "python*", "site-packages"))))
    except OSError:  # pragma: no cover
        pass
    for site_packages in candidates:
        package_dir = os.path.join(site_packages, "rvc_python")
        if not os.path.isdir(package_dir):
            continue
        info["engine_ok"] = True
        base_dir = os.path.join(package_dir, "base_model")
        info["base_models_dir"] = base_dir
        missing: List[str] = []
        for name in ("hubert_base.pt", "rmvpe.pt"):
            path = os.path.join(base_dir, name)
            try:
                if os.path.getsize(path) < BASEMODEL_MIN_BYTES:
                    missing.append("%s (troncato)" % name)
            except OSError:
                missing.append(name)
        info["missing_base_models"] = missing
        info["base_models_ok"] = not missing
        break
    return info
