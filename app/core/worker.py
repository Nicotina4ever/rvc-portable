"""Worker RVC persistente: processo unico che tiene il modello caldo.

Viene avviato dal backend ``app/core/engine_rvc.py`` con l'interprete del
runtime del motore (``runtime\\python.exe`` su Windows) e parla JSONL su
stdin/stdout:

    # richieste (stdin, una per riga)
    {"id":1,"op":"ping"}
    {"id":2,"op":"status"}
    {"id":3,"op":"load","model":"...pth","index":"...index","version":"v2","device":"cuda:0"}
    {"id":4,"op":"infer","input":"...wav","output":"...wav","params":{...}}
    {"id":5,"op":"cancel"}
    {"id":6,"op":"unload"}
    {"id":7,"op":"shutdown"}

    # risposte di controllo (stdout)
    {"ev":"result","id":3,"ok":true,"data":{"loaded":true,...}}
    {"ev":"error","id":3,"code":"model_invalid","message":"...","detail":"..."}

    # eventi asincroni durante infer
    {"ev":"stage","name":"f0","pct":30.0}
    {"ev":"log","message":"..."}
    {"ev":"done","id":4,"ok":true,"output":"...","duration_s":8.4,
     "sample_rate":48000,"elapsed_s":3.9,"frames":400000}
    {"ev":"error","id":4,"code":"canceled","message":"...","detail":"..."}

Note operative:

- **stdout e' riservato al protocollo**: all'avvio il file descriptor 1 viene
  duplicato per il protocollo e reindirizzato su stderr. Tutto cio' che stampa
  ``rvc_python``/``torch``/``fairseq`` finisce sullo stderr del worker, che il
  backend riversa nel log del motore (mai perso).
- l'ambiente (``CUDA_VISIBLE_DEVICES``) e' impostato dal backend **prima**
  dell'import di torch; il worker non importa torch finche' non riceve un
  ``load``.
- patch obbligatorie a ``rvc_python`` prima di costruire ``RVCInference``:
  niente download dei pesi base, niente riscrittura dei file in
  site-packages (``use_fp32_config``), niente MPS quando si forza la CPU.
- ``vc_single`` ritorna una stringa/tupla in caso di errore: il risultato
  viene validato (deve essere un ndarray non vuoto) prima di scrivere l'audio.
- l'output e' scritto in modo atomico (file temporaneo + ``os.replace``).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback
from typing import Any, Dict, Optional

LOGGER = logging.getLogger("rvc.worker")

WORKER_VERSION = 1
STAGE_LOADING = "loading"
STAGE_EXTRACT = "extract"
STAGE_F0 = "f0"
STAGE_FEATURES = "features"
STAGE_SYNTHESIZE = "synthesize"
STAGE_WRITE = "write"
STAGE_DONE = "done"

STAGE_PERCENT = {
    STAGE_LOADING: 0.0,
    STAGE_EXTRACT: 10.0,
    STAGE_F0: 30.0,
    STAGE_FEATURES: 55.0,
    STAGE_SYNTHESIZE: 75.0,
    STAGE_WRITE: 90.0,
    STAGE_DONE: 100.0,
}

F0_METHODS = ("rmvpe", "harvest", "crepe", "pm")
DEFAULT_PARAMS = {
    "pitch": 0,
    "method": "rmvpe",
    "protect": 0.33,
    "index_rate": 0.3,
    "filter_radius": 3,
    "rms_mix_rate": 0.25,
    "resample_sr": 0,
    "output_format": "wav",
}

# Stato condiviso con gli hook installati su rvc_python.modules.vc.pipeline:
# un solo job alla volta nel worker, quindi un dizionario globale e' sufficiente.
_HOOK: Dict[str, Any] = {
    "stage": None,
    "log": None,
    "cancel": None,
    "chunk_seen": False,
}


class WorkerError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class _InferenceCanceled(Exception):
    """Segnalata dagli hook quando il job viene annullato."""


# ---------------------------------------------------------------------------
# Protocollo
# ---------------------------------------------------------------------------


class ProtocolWriter:
    """Scrive righe JSON sul canale di protocollo in modo thread-safe."""

    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()
        self._broken = False

    def send(self, payload: Dict[str, Any]) -> None:
        if self._broken or self._stream is None:
            return
        try:
            line = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):  # pragma: no cover - payload interno
            line = json.dumps({"ev": "log", "message": "payload non serializzabile"})
        with self._lock:
            try:
                self._stream.write(line + "\n")
                self._stream.flush()
            except (OSError, ValueError):  # pipe chiusa dal backend
                self._broken = True

    def close(self) -> None:
        with self._lock:
            try:
                self._stream.flush()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass


def _setup_protocol_stream(log_path: Optional[str] = None):
    """Separa il canale protocollo (stdout) dai log (stderr)."""
    protocol = None
    try:
        protocol_fd = os.dup(1)
        protocol = os.fdopen(
            protocol_fd, "w", encoding="utf-8", buffering=1, newline="\n", errors="replace"
        )
        # Tutto cio' che scrive su fd 1 (anche a livello C) va su stderr.
        try:
            os.dup2(2, 1)
        except OSError:
            pass
    except (OSError, ValueError):
        protocol = sys.stdout

    stderr_stream = sys.stderr
    if stderr_stream is None:
        stderr_stream = _fallback_stderr(log_path)
        try:
            sys.stderr = stderr_stream
        except Exception:
            pass
    try:
        sys.stdout = stderr_stream
    except Exception:  # pragma: no cover
        pass
    logging.basicConfig(
        level=logging.INFO,
        stream=stderr_stream,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return protocol


def _fallback_stderr(log_path: Optional[str]):
    if log_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
            return open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    try:
        fd = os.dup(2)
        return os.fdopen(fd, "w", encoding="utf-8", buffering=1, errors="replace")
    except (OSError, ValueError):
        return _NullStream()


class _NullStream:
    def write(self, *args, **kwargs) -> int:
        return 0

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Hook su rvc_python
# ---------------------------------------------------------------------------


def _find_config_class(wrapper) -> Optional[type]:
    """Estrae la classe ``Config`` dalla closure del wrapper singleton.

    ``rvc_python.configs.config.Config`` e' decorata con ``@singleton_variable``:
    il nome esportato e' la funzione wrapper, quindi patchare il nome non
    raggiungerebbe i metodi della classe. Le closure sono l'unico riferimento
    pubblico alla classe originale.
    """
    for cell in getattr(wrapper, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:  # pragma: no cover - cella vuota
            continue
        if isinstance(value, type) and hasattr(value, "use_fp32_config"):
            return value
    return None


def patch_rvc_modules(force_cpu: bool = False) -> bool:
    """Applica le patch necessarie prima di costruire ``RVCInference``.

    Ritorna ``True`` se le patch sono state applicate.
    """
    from rvc_python.configs import config as config_module

    inner = _find_config_class(config_module.Config)
    if inner is not None:
        inner.use_fp32_config = lambda self: None
        if force_cpu:
            inner.has_mps = staticmethod(lambda: False)
        # ``Config`` e' singleton: una eventuale istanza gia' creata non deve
        # riscrivere i file, quindi patcheremo anche l'istanza corrente.
        instance = getattr(config_module.Config, "instance", None)
        if instance is not None:
            instance.use_fp32_config = lambda: None

    import rvc_python.infer as infer_module

    infer_module.download_rvc_models = lambda *args, **kwargs: None
    return inner is not None


def install_pipeline_hooks() -> bool:
    """Installa gli hook di stage/cancel sulla pipeline RVC (una sola volta)."""
    try:
        from rvc_python.modules.vc import pipeline as pipeline_module
    except Exception:  # pragma: no cover - dipende dal runtime
        return False
    pipeline_class = pipeline_module.Pipeline
    if getattr(pipeline_class, "_rvc_portable_hooks", False):
        return True

    original_get_f0 = pipeline_class.get_f0
    original_vc = pipeline_class.vc

    def get_f0(self, *args, **kwargs):
        _emit_stage(STAGE_F0)
        _check_cancel()
        return original_get_f0(self, *args, **kwargs)

    def vc(self, *args, **kwargs):
        if not _HOOK.get("chunk_seen"):
            _HOOK["chunk_seen"] = True
            _emit_stage(STAGE_FEATURES)
        _check_cancel()
        result = original_vc(self, *args, **kwargs)
        _check_cancel()
        _emit_stage(STAGE_SYNTHESIZE)
        return result

    pipeline_class.get_f0 = get_f0
    pipeline_class.vc = vc
    pipeline_class._rvc_portable_hooks = True
    return True


def _emit_stage(name: str, pct: Optional[float] = None) -> None:
    callback = _HOOK.get("stage")
    if not callable(callback):
        return
    try:
        callback(str(name), STAGE_PERCENT.get(name, pct) if pct is None else pct)
    except Exception:  # pragma: no cover - un callback rotto non ferma il job
        LOGGER.debug("emit_stage fallita", exc_info=True)


def _check_cancel() -> None:
    callback = _HOOK.get("cancel")
    if callable(callback) and callback():
        raise _InferenceCanceled()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class RvcWorker:
    """Esegue load/unload/infer sequenzialmente, con cancel cooperativo."""

    def __init__(self, requested_device: str = "auto", writer: Optional[ProtocolWriter] = None):
        self.requested_device = _normalize_requested_device(requested_device)
        self.device = self.requested_device
        self.started_at = time.time()
        self._writer = writer or ProtocolWriter(None)
        self._rvc = None
        self._torch = None
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._busy = False
        self._loaded = False
        self._model_path = ""
        self._index_path = ""
        self._version = "v2"
        self._last_activity = time.time()
        self._infer_count = 0
        self.warmup_error = ""

    # ------------------------------------------------------------------ state
    @property
    def busy(self) -> bool:
        return self._busy

    def request_cancel(self) -> None:
        self._cancel.set()

    def preload(self) -> Dict[str, Any]:
        """Import eager di torch/rvc_python PRIMA del thread reader.

        Su Windows il caricamento delle DLL di numpy/OpenBLAS (ctypes.CDLL)
        dentro un processo che ha gia' un thread bloccato su stdin va in
        deadlock nel loader. Il warm-up qui evita del tutto l'overlap: quando
        il reader parte, tutte le DLL pesanti sono gia' caricate.
        """
        self._emit_log_event("warm-up motore: import torch/rvc_python")
        try:
            self._ensure_rvc()
        except Exception as exc:
            self.warmup_error = "%s: %s" % (type(exc).__name__, exc)
            LOGGER.exception("warm-up del motore fallito")
            self._emit_log_event("warm-up motore FALLITO: %s" % self.warmup_error)
            raise WorkerError(
                "engine_error",
                "inizializzazione del motore fallita: %s" % exc,
                _tail(traceback.format_exc()),
            ) from exc
        data = self._status_data()
        self._emit_log_event(
            "motore pronto (torch %s, device %s)"
            % (data.get("torch") or "?", data.get("device") or "?")
        )
        return data

    def _status_data(self) -> Dict[str, Any]:
        actual_device = self.device
        tgt_sr = 0
        torch_version = ""
        cuda_available = None
        if self._rvc is not None:
            actual_device = str(getattr(getattr(self._rvc, "config", None), "device", self.device))
            tgt_sr = int(getattr(self._rvc.vc, "tgt_sr", 0) or 0)
        if self._torch is not None:
            torch_version = str(getattr(self._torch, "__version__", ""))
            try:
                cuda_available = bool(self._torch.cuda.is_available())
            except Exception:  # pragma: no cover
                cuda_available = False
        return {
            "worker_version": WORKER_VERSION,
            "pid": os.getpid(),
            "python": sys.version.split()[0],
            "torch": torch_version,
            "cuda_available": cuda_available,
            "requested_device": self.requested_device,
            "device": actual_device,
            "loaded": self._loaded,
            "model": self._model_path,
            "index": self._index_path,
            "version": self._version,
            "tgt_sr": tgt_sr,
            "busy": self._busy,
            "infer_count": self._infer_count,
            "uptime_s": round(time.time() - self.started_at, 2),
        }

    # ------------------------------------------------------------- lifecycle
    def _ensure_rvc(self):
        """Importa rvc_python/torch (una volta) e crea RVCInference."""
        if self._rvc is not None:
            return self._rvc
        self._emit_log_event("import di torch/rvc_python in corso (primo avvio)")
        import torch  # noqa: F401 - import pesante volutamente qui

        self._torch = torch
        from rvc_python.infer import RVCInference

        self.device = self._resolve_device()
        force_cpu = self.requested_device == "cpu"
        patched = patch_rvc_modules(force_cpu=force_cpu)
        if not patched:  # pragma: no cover - struttura rvc_python inattesa
            LOGGER.warning(
                "patch Config non applicate: possibili scritture in site-packages"
            )
        install_pipeline_hooks()
        self._emit_log_event("inizializzazione motore RVC su %s" % self.device)
        models_dir = os.path.join(os.getcwd(), "Modelli")
        self._rvc = RVCInference(models_dir=models_dir, device=self.device)
        actual = str(getattr(getattr(self._rvc, "config", None), "device", self.device))
        if actual != self.device:
            self._emit_log_event("device effettivo del motore: %s (richiesto %s)" % (actual, self.device))
        self.device = actual
        return self._rvc

    def _resolve_device(self) -> str:
        requested = self.requested_device
        torch = self._torch
        cuda_available = False
        mps_available = False
        if torch is not None:
            try:
                cuda_available = bool(torch.cuda.is_available())
            except Exception:
                cuda_available = False
            try:
                mps_available = bool(
                    getattr(torch.backends, "mps", None)
                    and torch.backends.mps.is_available()
                )
            except Exception:
                mps_available = False
        if requested == "auto":
            if cuda_available:
                return "cuda:0"
            if mps_available:
                return "mps"
            return "cpu"
        if requested.startswith("cuda"):
            if cuda_available:
                return requested
            self._emit_log_event("CUDA non disponibile nel worker: uso CPU")
            return "cpu"
        if requested == "mps":
            if mps_available:
                return "mps"
            self._emit_log_event("MPS non disponibile: uso CPU")
            return "cpu"
        return "cpu"

    def unload(self) -> None:
        with self._lock:
            if self._rvc is not None and self._loaded:
                try:
                    self._rvc.unload_model()
                except Exception:  # pragma: no cover
                    LOGGER.exception("unload del modello fallito")
                self._free_cuda()
            self._loaded = False
            self._model_path = ""
            self._index_path = ""
            self._version = "v2"

    def _free_cuda(self) -> None:
        try:
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------ ops
    def op_ping(self, request: Dict[str, Any]) -> None:
        self._send_result(
            request.get("id"),
            {"pong": True, "pid": os.getpid(), "device": self.device, "loaded": self._loaded},
        )

    def op_status(self, request: Dict[str, Any]) -> None:
        self._send_result(request.get("id"), self._status_data())

    def op_load(self, request: Dict[str, Any]) -> None:
        model = str(request.get("model") or "").strip()
        index = str(request.get("index") or "").strip()
        version = str(request.get("version") or "v2").strip().lower()
        if version not in ("v1", "v2"):
            version = "v2"
        if not model or not os.path.isfile(model):
            raise WorkerError("model_invalid", "modello non trovato: %s" % model)
        if index and not os.path.isfile(index):
            raise WorkerError("index_invalid", "indice non trovato: %s" % index)

        self._cancel.clear()
        self._emit_log_event("caricamento modello %s" % os.path.basename(model))
        if self.warmup_error and self._rvc is None:
            raise WorkerError(
                "engine_error",
                "warm-up del motore fallito, impossibile caricare il modello",
                self.warmup_error,
            )
        rvc = self._ensure_rvc()
        with self._lock:
            signature = (os.path.abspath(model), os.path.abspath(index) if index else "", version)
            current = (
                os.path.abspath(self._model_path) if self._model_path else "",
                os.path.abspath(self._index_path) if self._index_path else "",
                self._version,
            )
            if self._loaded and signature == current:
                self._send_result(request.get("id"), self._status_data())
                return
            if self._loaded:
                self._emit_log_event("scarico il modello precedente")
                try:
                    rvc.unload_model()
                except Exception:  # pragma: no cover
                    LOGGER.exception("unload prima del cambio modello fallito")
                self._free_cuda()
                self._loaded = False
            started = time.time()
            try:
                rvc.load_model(
                    os.path.abspath(model),
                    version=version,
                    index_path=os.path.abspath(index) if index else "",
                )
            except Exception as exc:
                raise WorkerError(
                    "model_invalid",
                    "impossibile caricare il modello: %s" % exc,
                    _tail(traceback.format_exc()),
                ) from exc
            self._loaded = True
            self._model_path = os.path.abspath(model)
            self._index_path = os.path.abspath(index) if index else ""
            self._version = version
            self._last_activity = time.time()
            elapsed = round(time.time() - started, 2)
        self._emit_log_event(
            "modello pronto in %ss (tgt_sr=%s)" % (elapsed, getattr(rvc.vc, "tgt_sr", "?"))
        )
        data = self._status_data()
        data["load_elapsed_s"] = elapsed
        self._send_result(request.get("id"), data)

    def op_unload(self, request: Dict[str, Any]) -> None:
        self.unload()
        data = self._status_data()
        data["unloaded"] = True
        self._send_result(request.get("id"), data)

    def op_infer(self, request: Dict[str, Any]) -> None:
        request_id = request.get("id")
        started = time.time()
        input_path = str(request.get("input") or "").strip()
        output_path = str(request.get("output") or "").strip()
        params = _normalize_params(request.get("params"))
        if not input_path or not os.path.isfile(input_path):
            raise WorkerError("input_missing", "file di input non trovato: %s" % input_path)
        if not output_path:
            raise WorkerError("validation_error", "percorso di output mancante")
        if self._rvc is None or not self._loaded:
            raise WorkerError(
                "engine_unavailable", "nessun modello caricato: invia prima 'load'"
            )
        if self.busy:
            raise WorkerError("engine_busy", "worker gia' occupato in un'altra inferenza")

        self._cancel.clear()
        self._busy = True
        self._set_infer_hooks(params)
        method = params["method"]
        if method not in F0_METHODS:
            method = "rmvpe"
        try:
            vc = self._rvc.vc
            self._rvc.set_params(
                f0method=method,
                f0up_key=int(params["pitch"]),
                index_rate=float(params["index_rate"]),
                filter_radius=int(params["filter_radius"]),
                resample_sr=int(params["resample_sr"]),
                rms_mix_rate=float(params["rms_mix_rate"]),
                protect=float(params["protect"]),
            )
            _emit_stage(STAGE_EXTRACT)
            self._emit_log_event(
                "inferenza su %s (metodo=%s, pitch=%+d, index_rate=%.2f)"
                % (os.path.basename(input_path), method, int(params["pitch"]), float(params["index_rate"]))
            )
            raw = vc.vc_single(
                sid=0,
                input_audio_path=os.path.abspath(input_path),
                f0_up_key=int(params["pitch"]),
                f0_file="",
                f0_method=method,
                file_index=self._index_path,
                file_index2="",
                index_rate=float(params["index_rate"]),
                filter_radius=int(params["filter_radius"]),
                resample_sr=int(params["resample_sr"]),
                rms_mix_rate=float(params["rms_mix_rate"]),
                protect=float(params["protect"]),
            )
            self._check_canceled()
            audio = _validate_audio_result(raw)
            sample_rate = _effective_sample_rate(
                int(getattr(vc, "tgt_sr", 0) or 0), int(params["resample_sr"])
            )
            if sample_rate <= 0:
                raise WorkerError(
                    "engine_error",
                    "sample rate di output non determinabile (tgt_sr=%r)" % getattr(vc, "tgt_sr", None),
                )
            _emit_stage(STAGE_WRITE)
            write_audio_atomic(
                output_path,
                audio,
                sample_rate,
                format_name=str(params["output_format"]),
            )
            self._check_canceled()
        except _InferenceCanceled:
            self._send_error(request_id, "canceled", "Job annullato")
            _emit_stage(STAGE_DONE)
            return
        finally:
            self._busy = False
            self._set_infer_hooks(None)
            self._last_activity = time.time()

        elapsed = round(time.time() - started, 3)
        frames = _audio_frames(audio)
        duration_s = round(float(frames) / float(sample_rate), 3)
        _emit_stage(STAGE_DONE)
        self._sender().send(
            {
                "ev": "done",
                "id": request_id,
                "ok": True,
                "output": os.path.abspath(output_path),
                "duration_s": duration_s,
                "sample_rate": int(sample_rate),
                "elapsed_s": elapsed,
                "frames": int(frames),
            }
        )
        self._infer_count += 1

    # ----------------------------------------------------------------- utils
    def _set_infer_hooks(self, params: Optional[Dict[str, Any]]) -> None:
        if params is None:
            _HOOK.update({"stage": None, "log": None, "cancel": None, "chunk_seen": False})
            return
        _HOOK.update(
            {
                "stage": self._emit_stage_event,
                "log": self._emit_log_event,
                "cancel": self._cancel.is_set,
                "chunk_seen": False,
            }
        )

    def _check_canceled(self) -> None:
        if self._cancel.is_set():
            raise _InferenceCanceled()

    def _sender(self) -> ProtocolWriter:
        return self._writer

    def _send_result(self, request_id, data: Dict[str, Any]) -> None:
        self._sender().send(
            {"ev": "result", "id": request_id, "ok": True, "data": data or {}}
        )

    def _send_error(self, request_id, code: str, message: str, detail: str = "") -> None:
        self._sender().send(
            {
                "ev": "error",
                "id": request_id,
                "ok": False,
                "code": code,
                "message": message,
                "detail": detail,
            }
        )

    def _emit_stage_event(self, name: str, pct: Optional[float]) -> None:
        payload: Dict[str, Any] = {"ev": "stage", "name": str(name)}
        if pct is not None:
            payload["pct"] = float(pct)
        self._sender().send(payload)

    def _emit_log_event(self, message: str) -> None:
        self._sender().send({"ev": "log", "message": str(message)})

    # ---------------------------------------------------------------- dispatch
    def handle(self, request: Dict[str, Any]) -> bool:
        """Gestisce una richiesta; ritorna ``False`` per terminare il worker."""
        if not isinstance(request, dict):
            return True
        op = str(request.get("op") or "")
        request_id = request.get("id")
        try:
            if op == "ping":
                self.op_ping(request)
            elif op == "status":
                self.op_status(request)
            elif op == "load":
                self.op_load(request)
            elif op == "infer":
                self.op_infer(request)
            elif op == "unload":
                self.op_unload(request)
            elif op == "cancel":
                self.request_cancel()
                self._send_result(request_id, {"canceled": True})
            elif op == "shutdown":
                self._send_result(request_id, {"shutdown": True})
                return False
            else:
                raise WorkerError("protocol_error", "operazione sconosciuta: %r" % op)
        except WorkerError as exc:
            self._send_error(request_id, exc.code, exc.message, exc.detail)
        except _InferenceCanceled:
            self._send_error(request_id, "canceled", "Job annullato")
        except Exception as exc:  # pragma: no cover - difensivo
            LOGGER.exception("errore inatteso nel worker (op=%s)", op)
            self._send_error(
                request_id,
                "engine_error",
                "errore interno del worker: %s" % exc,
                _tail(traceback.format_exc()),
            )
        return True

    def shutdown(self) -> None:
        try:
            self._cancel.set()
            self.unload()
        finally:
            self._free_cuda()


# ---------------------------------------------------------------------------
# Validazione / scrittura audio
# ---------------------------------------------------------------------------


def _normalize_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = dict(DEFAULT_PARAMS)
    if isinstance(params, dict):
        for key in result:
            if params.get(key) is not None:
                result[key] = params[key]
    try:
        result["pitch"] = int(result["pitch"])
    except (TypeError, ValueError):
        result["pitch"] = 0
    for key in ("protect", "index_rate", "rms_mix_rate"):
        try:
            result[key] = float(result[key])
        except (TypeError, ValueError):
            result[key] = DEFAULT_PARAMS[key]
    for key in ("filter_radius", "resample_sr"):
        try:
            result[key] = int(result[key])
        except (TypeError, ValueError):
            result[key] = DEFAULT_PARAMS[key]
    method = str(result.get("method") or "rmvpe").strip().lower()
    result["method"] = method if method in F0_METHODS else "rmvpe"
    fmt = str(result.get("output_format") or "wav").strip().lower()
    result["output_format"] = fmt if fmt in ("wav", "flac") else "wav"
    return result


def _normalize_requested_device(device: str) -> str:
    value = str(device or "auto").strip().lower()
    if value in ("", "auto"):
        return "auto"
    if value.startswith("dml"):
        # DirectML non e' supportato dal motore rvc-python.
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


def _validate_audio_result(raw) -> Any:
    """``vc_single`` ritorna un ndarray; stringa/tupla = errore interno."""
    if isinstance(raw, tuple):
        info = raw[0] if raw else "errore sconosciuto"
        raise WorkerError(
            "engine_error",
            "conversione fallita (rvc_python ha restituito un errore)",
            _tail(str(info or "")),
        )
    if isinstance(raw, str):
        raise WorkerError(
            "engine_error",
            "conversione fallita (rvc_python ha restituito un errore)",
            _tail(raw),
        )
    if raw is None:
        raise WorkerError("engine_error", "conversione fallita: output nullo")
    try:
        import numpy as np

        is_array = isinstance(raw, np.ndarray)
    except Exception:  # pragma: no cover - numpy sempre presente nel runtime
        is_array = hasattr(raw, "dtype") and hasattr(raw, "shape")
    if not is_array:
        raise WorkerError(
            "engine_error",
            "output del motore non valido: %s" % type(raw).__name__,
        )
    if raw.size == 0:
        raise WorkerError("engine_error", "output audio vuoto")
    return raw


def _effective_sample_rate(tgt_sr: int, resample_sr: int) -> int:
    """Replica la scelta di sample rate fatta da ``vc_single``."""
    if tgt_sr > 0 and resample_sr >= 16000 and tgt_sr != resample_sr:
        return int(resample_sr)
    return int(tgt_sr)


def _audio_frames(audio) -> int:
    try:
        shape = getattr(audio, "shape", None)
        if shape:
            return int(shape[0])
        return len(audio)
    except Exception:  # pragma: no cover
        return 0


def write_audio_atomic(
    path: str, audio, sample_rate: int, format_name: str = "wav"
) -> None:
    """Scrive WAV/FLAC in modo atomico (tmp nella stessa cartella + replace)."""
    import soundfile as sf

    destination = os.path.abspath(path)
    directory = os.path.dirname(destination)
    if directory:
        os.makedirs(directory, exist_ok=True)
    normalized_format = "FLAC" if str(format_name).lower() == "flac" else "WAV"
    if normalized_format == "FLAC" and not destination.lower().endswith(".flac"):
        destination += ".flac"
    tmp = destination + ".part-%d" % os.getpid()
    try:
        sf.write(tmp, audio, int(sample_rate), format=normalized_format, subtype="PCM_16")
        os.replace(tmp, destination)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:  # pragma: no cover
            pass


def _tail(text: str, limit: int = 4000) -> str:
    value = str(text or "").strip()
    return value[-limit:] if len(value) > limit else value


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rvc-worker", description="Worker RVC persistente (JSONL su stdio)"
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="device logico del worker: auto|cpu|cuda:N|mps "
        "(CUDA_VISIBLE_DEVICES e' impostata dal backend)",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="file di log di fallback quando stderr non e' disponibile (pythonw)",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    protocol = _setup_protocol_stream(args.log_file or None)
    if os.environ.get("RVC_WORKER_DEBUG"):
        # Diagnostica: dump dello stack su stderr se un'operazione si blocca.
        import faulthandler

        faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)
    writer = ProtocolWriter(protocol)
    worker = RvcWorker(requested_device=args.device, writer=writer)
    LOGGER.info("worker RVC avviato (device=%s)", worker.device)
    writer.send({"ev": "log", "message": "worker avviato (device=%s)" % worker.device})

    # IMPORTANTE (Windows): il warm-up di torch/numpy/rvc_python deve avvenire
    # PRIMA di avviare il thread reader su stdin. Se un thread e' bloccato su
    # stdin mentre il loader carica le DLL di numpy/OpenBLAS, ctypes.CDLL va in
    # deadlock (verificato con stack dump: numpy/_distributor_init -> ctypes).
    try:
        worker.preload()
    except WorkerError as exc:
        LOGGER.error("warm-up del motore fallito: %s", exc.message)
    except Exception:  # pragma: no cover - difensivo
        LOGGER.exception("warm-up del motore fallito in modo inatteso")

    requests: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
    stop_reading = threading.Event()

    def reader() -> None:
        stream = sys.stdin
        if stream is None:  # pragma: no cover - pythonw senza stdin
            requests.put(None)
            return
        try:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except ValueError:
                    writer.send(
                        {
                            "ev": "error",
                            "id": 0,
                            "ok": False,
                            "code": "protocol_error",
                            "message": "riga JSON non valida",
                        }
                    )
                    continue
                if not isinstance(request, dict):
                    continue
                op = str(request.get("op") or "")
                if op == "cancel":
                    # Il cancel deve essere immediato anche mentre infer gira.
                    worker.request_cancel()
                    writer.send(
                        {"ev": "result", "id": request.get("id"), "ok": True,
                         "data": {"canceled": True}}
                    )
                    continue
                if op == "shutdown" and worker.busy:
                    worker.request_cancel()
                requests.put(request)
        except (OSError, ValueError):  # stdin chiuso dal backend
            pass
        finally:
            stop_reading.set()
            requests.put(None)

    threading.Thread(target=reader, name="rvc-worker-stdin", daemon=True).start()
    LOGGER.info("worker pronto, in attesa di richieste")
    try:
        while True:
            request = requests.get()
            if request is None:
                break
            if not worker.handle(request):
                break
    except KeyboardInterrupt:  # pragma: no cover
        LOGGER.info("worker interrotto da tastiera")
    finally:
        try:
            worker.shutdown()
        except Exception:  # pragma: no cover
            LOGGER.exception("shutdown del worker fallito")
        writer.send({"ev": "log", "message": "worker terminato"})
        writer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
