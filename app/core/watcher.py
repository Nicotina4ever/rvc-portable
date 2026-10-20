"""Monitoraggio cartelle: rileva file audio completi e li accoda ai job.

Contratto (docs/API-CONTRACT.md):

    Watcher(on_file=lambda path: ..., on_state=lambda status: ..., settings_manager=..., job_queue=...)
    .start(directory: str, process_existing: bool = False) -> dict
    .stop() -> dict
    .status() -> dict   # {"running", "dir", "mode", "processed_session"}
    .process_existing(directory: Optional[str] = None) -> dict  # {"enqueued", "skipped"}

Caratteristiche:

- ``watchdog`` NativeObserver per i path locali, PollingObserver per UNC/rete
  (o quando ``watch_mode = "polling"``); fallback a scansione periodica se
  ``watchdog`` non e' importabile;
- stabilita' del file basata su dimensione + mtime (``stability_ms``): un file
  copiato/ancora in scrittura non viene processato a meta';
- ``ignore_globs`` e cartella di output ignorate;
- dedupe **persistente** in ``data/state/processed.json`` (chiave = percorso,
  valore = dimensione + mtime): un file gia' convertito non viene riconvertito
  a ogni riavvio, ma un file modificato si';
- callbacks eseguiti su thread dedicati (mai Tk): ``on_file(path)`` e
  ``on_state(status)``;
- nessuna modifica ai file monitorati.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

LOGGER = logging.getLogger("rvc.watcher")

AUDIO_EXTENSIONS = (
    ".wav",
    ".mp3",
    ".ogg",
    ".m4a",
    ".flac",
    ".aac",
    ".opus",
    ".wma",
)
DEFAULT_IGNORE_GLOBS = ["*.tmp", "*.part", "*.crdownload", "~$*", ".*"]
DEFAULT_STABILITY_MS = 1500
DEFAULT_POLL_INTERVAL_S = 2.0
TICK_S = 0.1
PROCESSED_VERSION = 1
PROCESSED_MAX_ENTRIES = 5000


class Watcher:
    """Osservatore di una cartella con accodamento dei file audio stabili."""

    def __init__(
        self,
        on_file: Optional[Callable[[str], Any]] = None,
        on_state: Optional[Callable[[Dict[str, Any]], Any]] = None,
        settings_manager=None,
        job_queue=None,
        processed_path: Optional[str] = None,
    ):
        self._on_file = on_file
        self._on_state = on_state
        self.settings_manager = settings_manager
        self.job_queue = job_queue
        self.directory = ""

        self._lock = threading.RLock()
        self._observer = None
        self._thread: Optional[threading.Thread] = None
        self._run_event = threading.Event()
        self._events: "queue.Queue[Optional[str]]" = queue.Queue()
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._processed: Dict[str, Dict[str, Any]] = {}
        self._session_seen: Dict[str, Dict[str, Any]] = {}
        self._processed_session = 0
        self._running = False
        self._mode = "none"
        self._manual_scan = False
        self._next_scan = 0.0
        self._stability_ms = DEFAULT_STABILITY_MS
        self._poll_interval_s = DEFAULT_POLL_INTERVAL_S
        self._ignore_globs: List[str] = list(DEFAULT_IGNORE_GLOBS)
        self._ignore_output_dir = True
        self._processed_path = processed_path or self._default_processed_path()
        self._load_processed()

    # ------------------------------------------------------------------ state
    @property
    def is_running(self) -> bool:
        return bool(self._running)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            running = bool(self._running and self._thread_alive())
            queued = None
            if self.job_queue is not None:
                try:
                    queued = int(self.job_queue.stats().get("pending", 0))
                except Exception:
                    queued = None
            payload: Dict[str, Any] = {
                "running": running,
                "dir": self.directory,
                "mode": self._mode,
                "processed_session": int(self._processed_session),
            }
            if queued is not None:
                payload["queued"] = queued
            return payload

    def _thread_alive(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    # -------------------------------------------------------------- lifecycle
    def start(self, directory: str, process_existing: bool = False) -> Dict[str, Any]:
        target = self._normalize_directory(directory)
        if not os.path.isdir(target):
            raise ValueError("cartella da monitorare non trovata: %s" % target)
        if self._running:
            self.stop()

        self._refresh_settings()
        with self._lock:
            self.directory = target
            self._mode = self._choose_mode(target)
            self._processed_session = 0
            self._session_seen = {}
            self._pending = {}
            self._drain_events()

        self._observer, self._manual_scan = self._create_observer()
        self._run_event.set()
        self._next_scan = time.time() + self._poll_interval_s
        self._thread = threading.Thread(
            target=self._monitor_loop, name="rvc-watcher", daemon=True
        )
        self._thread.start()
        with self._lock:
            self._running = True

        if self._observer is not None:
            try:
                self._observer.schedule(self._handler, target, recursive=False)
                self._observer.start()
            except Exception as exc:
                LOGGER.exception("observer non avviabile, uso la scansione periodica")
                self._observer = None
                self._manual_scan = True
                self._mode = "polling"
                LOGGER.warning("monitor: fallback polling (%s)", exc)

        LOGGER.info("monitor avviato su %s (mode=%s)", target, self._mode)
        if process_existing:
            self.process_existing(target)
        status = self.status()
        self._notify(status)
        return status

    def stop(self) -> Dict[str, Any]:
        observer = self._observer
        self._observer = None
        self._run_event.clear()
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=5.0)
            except Exception:  # pragma: no cover - watchdog edge
                LOGGER.exception("stop dell'observer fallito")
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        try:
            self._events.put_nowait(None)
        except queue.Full:  # pragma: no cover
            pass
        with self._lock:
            was_running = self._running
            self._running = False
            self._mode = "none"
            self._pending = {}
            self._session_seen = {}
        if was_running:
            LOGGER.info("monitor fermato (%s)", self.directory)
        status = self.status()
        if was_running:
            self._notify(status)
        return status

    # -------------------------------------------------------------- existing
    def process_existing(self, directory: Optional[str] = None) -> Dict[str, Any]:
        target = self._normalize_directory(directory or self.directory)
        if not target or not os.path.isdir(target):
            raise ValueError("cartella da processare non trovata: %s" % target)
        self._refresh_settings()
        enqueued = 0
        skipped = 0
        try:
            entries = sorted(os.scandir(target), key=lambda item: item.name.lower())
        except OSError as exc:
            raise ValueError("cartella non leggibile: %s (%s)" % (target, exc)) from exc
        for entry in entries:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            path = entry.path
            if not self._is_audio(path):
                continue
            if self._is_ignored(path) or self._already_processed(path):
                skipped += 1
                continue
            if self._dispatch(path):
                enqueued += 1
            else:
                skipped += 1
        if enqueued:
            self._notify(self.status())
        return {"enqueued": enqueued, "skipped": skipped}

    # ---------------------------------------------------------------- internals
    def _normalize_directory(self, directory: Optional[str]) -> str:
        value = str(directory or "").strip().strip('"')
        if not value:
            return ""
        return os.path.abspath(os.path.expanduser(value))

    def _refresh_settings(self) -> None:
        monitor = None
        try:
            monitor = self.settings_manager.settings.monitor
        except Exception:
            monitor = None
        if monitor is None:
            return
        self._stability_ms = max(
            0, int(getattr(monitor, "stability_ms", DEFAULT_STABILITY_MS) or 0)
        )
        self._poll_interval_s = max(
            0.5, float(getattr(monitor, "poll_interval_s", DEFAULT_POLL_INTERVAL_S) or 0.5)
        )
        globs = getattr(monitor, "ignore_globs", None)
        self._ignore_globs = (
            [str(item) for item in globs] if isinstance(globs, (list, tuple)) else list(DEFAULT_IGNORE_GLOBS)
        )
        self._ignore_output_dir = bool(getattr(monitor, "ignore_output_dir", True))

    def _choose_mode(self, directory: str) -> str:
        requested = "auto"
        try:
            requested = str(self.settings_manager.settings.monitor.watch_mode or "auto")
        except Exception:
            requested = "auto"
        requested = requested.strip().lower()
        if requested in ("native", "polling"):
            if requested == "native" and _is_unc(directory):
                LOGGER.info("path UNC: forzo il polling per %s", directory)
                return "polling"
            return requested
        if _is_unc(directory):
            return "polling"
        return "native"

    def _create_observer(self):
        if self._mode == "polling":
            try:
                from watchdog.observers.polling import PollingObserver

                return PollingObserver(timeout=self._poll_interval_s), False
            except Exception as exc:
                LOGGER.warning("PollingObserver non disponibile (%s): scansione interna", exc)
                return None, True
        try:
            from watchdog.observers import Observer

            return Observer(), False
        except Exception as exc:
            LOGGER.warning("watchdog non disponibile (%s): scansione interna", exc)
            self._mode = "polling"
            return None, True

    @property
    def _handler(self):
        handler = getattr(self, "_handler_instance", None)
        if handler is not None:
            return handler
        handler = _create_handler(self)
        self._handler_instance = handler
        return handler

    # ------------------------------------------------------------------ events
    def _monitor_loop(self) -> None:
        while self._run_event.is_set():
            try:
                path = self._events.get(timeout=TICK_S)
            except queue.Empty:
                path = None
            if path:
                self._schedule(path)
            self._process_pending()
            if self._manual_scan and time.time() >= self._next_scan:
                self._next_scan = time.time() + self._poll_interval_s
                self._scan_directory()

    def _drain_events(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def _scan_directory(self) -> None:
        try:
            entries = list(os.scandir(self.directory))
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False):
                    self._schedule(entry.path)
            except OSError:
                continue

    def _schedule(self, path: str) -> None:
        if not path or self._is_ignored(path) or not self._is_audio(path):
            return
        try:
            stat = os.stat(path)
        except OSError:
            return
        if not os.path.isfile(path):
            return
        key = _path_key(path)
        now = time.time()
        stamp = (int(stat.st_size), _mtime_ns(stat))
        with self._lock:
            entry = self._pending.get(key)
            if entry is None:
                entry = {
                    "path": path,
                    "size": stamp[0],
                    "mtime_ns": stamp[1],
                    "last_change": now,
                    "added": now,
                }
                self._pending[key] = entry
            elif (entry["size"], entry["mtime_ns"]) != stamp:
                entry["size"], entry["mtime_ns"] = stamp
                entry["last_change"] = now

    def _process_pending(self) -> None:
        now = time.time()
        with self._lock:
            items = list(self._pending.items())
        for key, entry in items:
            try:
                stat = os.stat(entry["path"])
            except OSError:
                with self._lock:
                    self._pending.pop(key, None)
                continue
            stamp = (int(stat.st_size), _mtime_ns(stat))
            if stamp != (entry["size"], entry["mtime_ns"]):
                with self._lock:
                    entry["size"], entry["mtime_ns"] = stamp
                    entry["last_change"] = now
                continue
            stable_s = (now - entry["last_change"]) * 1000.0
            if self._stability_ms <= 0 or stable_s >= self._stability_ms:
                with self._lock:
                    self._pending.pop(key, None)
                self._dispatch(entry["path"])

    # --------------------------------------------------------------- dispatch
    def _dispatch(self, path: str) -> bool:
        if self._is_ignored(path) or self._already_processed(path):
            return False
        try:
            handler = self._on_file
            if callable(handler):
                handler(path)
            elif self.job_queue is not None:
                self._enqueue_default(path)
            else:
                LOGGER.warning("monitor: nessun gestore per %s", path)
                return False
        except Exception as exc:
            LOGGER.error("monitor: accodamento fallito per %s: %s", path, exc)
            return False

        fingerprint = self._fingerprint(path)
        key = _path_key(path)
        with self._lock:
            self._processed[key] = {
                "size": fingerprint[0],
                "mtime_ns": fingerprint[1],
                "ts": time.time(),
            }
            self._session_seen[key] = {
                "size": fingerprint[0],
                "mtime_ns": fingerprint[1],
            }
            self._processed_session += 1
            self._trim_processed()
        self._save_processed()
        LOGGER.info("monitor: accodato %s", os.path.basename(path))
        self._notify(self.status())
        return True

    def _enqueue_default(self, path: str) -> None:
        from .engine import InferParams

        audio = self.settings_manager.settings.audio
        self.job_queue.enqueue(path, InferParams.from_audio(audio), source="monitor")

    def _notify(self, status: Dict[str, Any]) -> None:
        callback = self._on_state
        if not callable(callback):
            return
        try:
            callback(dict(status))
        except Exception:  # pragma: no cover - un callback rotto non ferma il watcher
            LOGGER.exception("monitor: callback on_state fallita")

    # -------------------------------------------------------------- filtering
    def _is_audio(self, path: str) -> bool:
        return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS

    def _is_ignored(self, path: str) -> bool:
        name = os.path.basename(path)
        lowered_name = name.lower()
        for pattern in self._ignore_globs:
            candidate = str(pattern or "").lower()
            if not candidate:
                continue
            if fnmatch.fnmatch(lowered_name, candidate) or fnmatch.fnmatch(
                path.lower(), candidate
            ):
                return True
        if self._ignore_output_dir:
            output_dir = ""
            try:
                output_dir = str(self.settings_manager.settings.audio.output_dir or "")
            except Exception:
                output_dir = ""
            if output_dir and _is_within(path, output_dir):
                return True
        return False

    def _fingerprint(self, path: str):
        try:
            stat = os.stat(path)
        except OSError:
            return (0, 0)
        return (int(stat.st_size), _mtime_ns(stat))

    def _already_processed(self, path: str) -> bool:
        key = _path_key(path)
        fingerprint = self._fingerprint(path)
        with self._lock:
            session = self._session_seen.get(key)
            if session is not None and (session["size"], session["mtime_ns"]) == fingerprint:
                return True
            stored = self._processed.get(key)
            if stored is not None and (stored["size"], stored["mtime_ns"]) == fingerprint:
                return True
        return False

    # ------------------------------------------------------------- persistence
    def _default_processed_path(self) -> Optional[str]:
        try:
            paths = self.settings_manager.paths
            return paths.processed_state_path
        except Exception:
            return None

    def _load_processed(self) -> None:
        path = self._processed_path
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            LOGGER.warning("processed.json illeggibile: %s", path)
            return
        if not isinstance(data, dict):
            return
        files = data.get("files")
        if not isinstance(files, dict):
            return
        loaded: Dict[str, Dict[str, Any]] = {}
        for key, value in files.items():
            if not isinstance(value, dict):
                continue
            try:
                loaded[str(key)] = {
                    "size": int(value.get("size", -1)),
                    "mtime_ns": int(value.get("mtime_ns", -1)),
                    "ts": float(value.get("ts", 0.0)),
                }
            except (TypeError, ValueError):
                continue
        with self._lock:
            self._processed = loaded

    def _save_processed(self) -> None:
        path = self._processed_path
        if not path:
            return
        with self._lock:
            payload = {
                "version": PROCESSED_VERSION,
                "files": dict(self._processed),
            }
        tmp = "%s.tmp-%d" % (path, os.getpid())
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as exc:
            LOGGER.warning("processed.json non salvabile (%s): %s", path, exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    def _trim_processed(self) -> None:
        if len(self._processed) <= PROCESSED_MAX_ENTRIES:
            return
        ordered = sorted(
            self._processed.items(), key=lambda item: item[1].get("ts", 0.0)
        )
        remove = len(ordered) - PROCESSED_MAX_ENTRIES
        for key, _ in ordered[:remove]:
            self._processed.pop(key, None)


# ---------------------------------------------------------------------------
# Helper watchdog (import lazy per non caricare watchdog nel backend web)
# ---------------------------------------------------------------------------


def _create_handler(watcher: Watcher):
    from watchdog.events import FileSystemEventHandler

    class _WatcherHandler(FileSystemEventHandler):
        def on_created(self, event):  # noqa: D401,N802
            _queue_event(watcher, event, ("src_path",))

        def on_modified(self, event):  # noqa: N802
            _queue_event(watcher, event, ("src_path",))

        def on_moved(self, event):  # noqa: N802
            _queue_event(watcher, event, ("dest_path", "src_path"))

    return _WatcherHandler()


def _queue_event(watcher: Watcher, event, attributes) -> None:
    if getattr(event, "is_directory", False):
        return
    for attribute in attributes:
        path = getattr(event, attribute, "") or ""
        if path:
            try:
                watcher._events.put_nowait(path)  # noqa: SLF001 - handler interno
            except queue.Full:  # pragma: no cover
                pass


def _is_unc(directory: str) -> bool:
    value = str(directory or "")
    return value.startswith("\\\\") or value.startswith("//")


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _mtime_ns(stat) -> int:
    return int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)))


def _is_within(path: str, directory: str) -> bool:
    try:
        candidate = os.path.normcase(os.path.abspath(path))
        root = os.path.normcase(os.path.abspath(directory)).rstrip("\\/")
    except (OSError, ValueError):
        return False
    return candidate == root or candidate.startswith(root + os.sep)
