"""Logging su file con buffer circolare e hook per errori fatali.

Pensato per ``pythonw``: quando non c'e' console, stdout/stderr sono None e un
semplice ``print`` puo' sollevare eccezioni. Il launcher redirige gli stream
prima di importare il motore; qui si configura il logging su file, il buffer
per la UI (SSE) e i gestori di eccezioni non catturate.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import traceback
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

from . import events
from .paths import AppPaths

APP_LOGGER = "rvc"
_configured = False
_ring: Optional["RingBufferHandler"] = None


class RingBufferHandler(logging.Handler):
    """Tiene gli ultimi N record e li pubblica sul bus eventi."""

    def __init__(self, bus, maxlen: int = 2000):
        super().__init__()
        self._records: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._bus = bus

    @property
    def records(self):
        with self._lock:
            return list(self._records)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": record.created,
                "level": record.levelname.lower(),
                "source": record.name,
                "message": record.getMessage(),
            }
            code = getattr(record, "code", None)
            params = getattr(record, "params", None)
            if code:
                entry["code"] = code
            if params:
                entry["params"] = params
            with self._lock:
                self._records.append(entry)
            if record.levelno >= logging.INFO:
                self._bus.publish("log", entry)
        except Exception:  # pragma: no cover - il logging non deve mai crashare
            pass


def setup_logging(
    paths: AppPaths,
    console: bool = False,
    level: str = "INFO",
    bus=None,
) -> logging.Logger:
    """Configura il logger applicativo (idempotente)."""
    global _configured, _ring

    logger = logging.getLogger(APP_LOGGER)
    if _configured:
        return logger

    numeric_level = getattr(logging, str(level).upper(), logging.INFO)
    logger.setLevel(numeric_level)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    os.makedirs(paths.logs_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        paths.app_log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    _ring = RingBufferHandler(bus or events.BUS)
    _ring.setLevel(logging.DEBUG)
    logger.addHandler(_ring)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("watchdog").setLevel(logging.WARNING)

    _configured = True
    return logger


def get_logger(name: str = APP_LOGGER) -> logging.Logger:
    if name == APP_LOGGER:
        return logging.getLogger(APP_LOGGER)
    return logging.getLogger(name)


def get_ring_records():
    return _ring.records if _ring else []


def install_excepthooks(
    on_fatal: Optional[Callable[[str], None]] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Logga eccezioni del thread principale e dei thread secondari."""
    log = logger or logging.getLogger(APP_LOGGER)
    original_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("Eccezione non gestita:\n%s", text)
        if on_fatal:
            try:
                on_fatal(text)
            except Exception:
                pass
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook

    def _thread_hook(args):
        text = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        log.critical(
            "Eccezione non gestita nel thread %s:\n%s",
            getattr(args.thread, "name", "?"),
            text,
        )

    threading.excepthook = _thread_hook


def redirect_std_streams(paths: AppPaths) -> None:
    """Sotto pythonw stdout/stderr sono None: li manda su file (o devnull)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    os.makedirs(paths.logs_dir, exist_ok=True)
    try:
        stream = open(paths.stdout_log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
