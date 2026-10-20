"""Launcher: avvia backend, apre l'interfaccia e gestisce il ciclo di vita.

Pensato per funzionare anche sotto ``pythonw.exe`` (Windows, nessuna console):
- redirige stdout/stderr su file prima di importare il motore;
- logga ogni errore e mostra un dialog nativo in caso di crash;
- garantisce una sola istanza e riapre quella esistente;
- chiude il server quando la finestra app viene chiusa (o per inattivita').
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Optional, Tuple

from . import __version__, events
from .api.app_factory import create_app
from .core.engine import NullEngine
from .core.jobs import JobQueue
from .logging_setup import (
    install_excepthooks,
    redirect_std_streams,
    setup_logging,
)
from .paths import AppPaths
from .security import (
    SessionInfo,
    SessionStore,
    find_free_port,
    new_token,
    subprocess_no_window,
)
from .settings import SettingsManager

LOGGER = logging.getLogger("rvc.launcher")

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def run(paths: AppPaths, args) -> int:
    redirect_std_streams(paths)
    logger = setup_logging(paths, console=bool(args.console), level=args.log_level)
    install_excepthooks(
        on_fatal=lambda text: _fatal_dialog(
            "RVC Portable — errore", text, paths.app_log_path, args
        ),
        logger=logger,
    )
    logger.info("avvio RVC Portable %s (root=%s)", __version__, paths.app_root)

    manager = SettingsManager(paths)
    try:
        manager.load()
    except Exception as exc:
        logger.exception("configurazione non caricabile: %s", exc)
    for warning in manager.warnings:
        logger.warning("config: %s", warning)

    store = SessionStore(paths)
    existing = _existing_instance(paths)
    if existing is not None and not args.port:
        url = "http://127.0.0.1:%d/?t=%s" % (existing.port, existing.token)
        logger.info("istanza gia' attiva (pid %s): apro %s", existing.pid, url)
        _open_existing(url, args)
        return 0

    port = args.port or find_free_port(args.host)
    token = new_token()
    session = SessionInfo(
        token=token,
        port=port,
        pid=os.getpid(),
        started_at=time.time(),
        host=args.host,
    )
    store.save(session)
    _write_instance(paths, session)

    engine = _build_engine(paths, manager, logger)
    queue = JobQueue(
        engine,
        manager,
        events.BUS,
        jobs_state_path=paths.jobs_state_path,
    )
    queue.start()

    watcher = _build_watcher(paths, manager, queue, logger)
    config_sync = _build_config_sync(manager, logger)
    status_publisher = _build_status_publisher(manager, engine, queue, watcher, config_sync, logger)

    app = create_app(
        paths=paths,
        settings_manager=manager,
        engine=engine,
        job_queue=queue,
        watcher=watcher,
        bus=events.BUS,
        token=token,
        port=port,
        allow_lan=bool(args.allow_lan),
    )
    app.state.config_sync = config_sync
    app.state.status_publisher = status_publisher
    shutdown_event = threading.Event()
    app.state.shutdown_callback = shutdown_event.set

    server = _start_server(app, args.host, port, logger)
    try:
        if not _wait_health(port, timeout=45.0):
            raise RuntimeError("il backend non risponde su 127.0.0.1:%d" % port)

        _autostart_monitor(manager, watcher, logger)

        url = "http://127.0.0.1:%d/?t=%s" % (port, token)
        logger.info(
            "backend pronto su http://127.0.0.1:%d (token in data/state/session.json)",
            port,
        )

        if args.headless or args.browser == "none":
            print(url, flush=True)
            _wait_for_shutdown(shutdown_event, args, queue, paths)
        else:
            _run_with_browser(url, args, paths, shutdown_event, queue)
    finally:
        logger.info("spegnimento in corso")
        try:
            status_publisher.stop()
        except Exception:
            pass
        try:
            config_sync.stop()
        except Exception:
            pass
        try:
            watcher.stop()
        except Exception:
            pass
        try:
            queue.stop()
        except Exception:
            pass
        server.should_exit = True
        for _ in range(100):
            if not getattr(server, "started", False):
                break
            time.sleep(0.05)
        store.clear()
        _clear_instance(paths)
        logger.info("applicazione terminata")
    return 0


# ---------------------------------------------------------------------------
# Componenti
# ---------------------------------------------------------------------------


def _build_engine(paths: AppPaths, manager: SettingsManager, logger):
    try:
        from .core.engine_rvc import create_engine

        engine = create_engine(paths, settings_manager=manager)
    except Exception as exc:
        logger.exception("impossibile creare il motore: %s", exc)
        return NullEngine("Motore non inizializzabile: %s" % exc)
    try:
        status = engine.status()
        if not status.available:
            logger.warning("motore non disponibile: %s", status.message)
    except Exception:
        pass
    return engine


def _autostart_monitor(manager, watcher, logger) -> None:
    """Avvia il monitoraggio all'apertura se configurato (flusso Dropbox/Android)."""
    if watcher is None:
        return
    try:
        settings = manager.settings
        if not settings.monitor.enabled_on_start:
            return
        directory = str(settings.audio.input_dir or "")
        if not directory or not os.path.isdir(directory):
            logger.warning("monitor: cartella input non valida, avvio automatico saltato")
            return
        status = watcher.start(
            directory, process_existing=bool(settings.monitor.process_existing)
        )
        logger.info("monitor avviato automaticamente su %s", status.get("dir", directory))
    except Exception as exc:  # pragma: no cover - non blocca l'avvio
        logger.warning("monitor: avvio automatico fallito: %s", exc)


def _build_status_publisher(manager, engine, queue, watcher, config_sync, logger):
    """Scrive status.json per il controllo remoto dall'app Android."""
    try:
        from .android_bridge import StatusPublisher

        providers = {
            "engine": lambda: engine.status(),
            "queue": lambda: queue.stats(),
            "watcher": lambda: watcher.status() if watcher is not None else {},
            "config": lambda: config_sync.status() if config_sync is not None else {},
        }
        publisher = StatusPublisher(manager, providers)
        publisher.start()
        return publisher
    except Exception as exc:  # pragma: no cover - non blocca l'avvio
        logger.exception("status publisher non inizializzabile: %s", exc)
        return None


def _build_config_sync(manager, logger):
    """Hot reload del config condiviso (Dropbox locale / app Android)."""
    try:
        from .android_bridge import ConfigSync

        sync = ConfigSync(manager, bus=events.BUS)
        sync.start()
        return sync
    except Exception as exc:  # pragma: no cover - non blocca l'avvio
        logger.exception("config sync non inizializzabile: %s", exc)
        return None


def _build_watcher(paths: AppPaths, manager: SettingsManager, queue: JobQueue, logger):
    try:
        from .core.watcher import Watcher
    except Exception:  # pragma: no cover
        return None

    def on_file(file_path: str):
        from .core.engine import InferParams

        try:
            queue.enqueue(
                file_path,
                InferParams.from_audio(manager.settings.audio),
                source="monitor",
            )
        except Exception as exc:
            logger.error("monitor: impossibile accodare %s: %s", file_path, exc)

    def on_state(state: dict):
        events.BUS.publish("monitor", state or {})

    try:
        return Watcher(
            on_file=on_file,
            on_state=on_state,
            settings_manager=manager,
            job_queue=queue,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("watcher non inizializzabile: %s", exc)
        return None


def _start_server(app, host: str, port: int, logger):
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="rvc-http", daemon=True)
    thread.start()
    for _ in range(200):
        if getattr(server, "started", False):
            break
        time.sleep(0.05)
    logger.info("server HTTP avviato su %s:%s", host, port)
    return server


def _wait_for_shutdown(shutdown_event, args, queue, paths: AppPaths) -> None:
    idle_minutes = int(getattr(args, "idle_exit_minutes", 0) or 0)
    no_client_since: Optional[float] = None
    while not shutdown_event.is_set():
        try:
            shutdown_event.wait(timeout=5.0)
        except KeyboardInterrupt:
            return
        if shutdown_event.is_set():
            return
        if idle_minutes <= 0:
            continue
        clients = events.BUS.subscriber_count
        if clients > 0:
            no_client_since = None
        elif no_client_since is None:
            no_client_since = time.time()
        elif (time.time() - no_client_since) > idle_minutes * 60:
            LOGGER.info("nessun client connesso da %s minuti: spegnimento", idle_minutes)
            return


def _run_with_browser(url, args, paths: AppPaths, shutdown_event, queue) -> None:
    process, mode = _open_browser(url, args, paths)
    LOGGER.info("interfaccia aperta (%s)", mode)
    if process is not None:
        try:
            process.wait()
        except Exception:
            pass
        # Se il processo termina subito ma la pagina e' ancora connessa,
        # lasciamo vivere il server (chiusura delegata all'idle-exit).
        time.sleep(0.5)
        if events.BUS.subscriber_count == 0:
            return
    _wait_for_shutdown(shutdown_event, args, queue, paths)


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------


def _browser_path(kind: str) -> Optional[str]:
    if kind == "edge":
        candidates = EDGE_CANDIDATES
    elif kind == "chrome":
        candidates = CHROME_CANDIDATES
    else:
        candidates = CHROME_CANDIDATES + EDGE_CANDIDATES
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    if kind in ("auto", "chrome"):
        for name in ("google-chrome", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                return found
    return None


def _open_browser(url: str, args, paths: AppPaths) -> Tuple[Optional[subprocess.Popen], str]:
    if args.browser == "default":
        webbrowser.open(url)
        return None, "default"
    executable = _browser_path(args.browser)
    if executable and args.app_mode:
        args_list = [
            executable,
            "--app=%s" % url,
            "--user-data-dir=%s" % paths.browser_profile_dir,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--window-size=1280,860",
        ]
        try:
            process = subprocess.Popen(
                args_list,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **subprocess_no_window(),
            )
            return process, "app-mode"
        except OSError:
            LOGGER.exception("apertura app-mode fallita, uso il browser predefinito")
    try:
        webbrowser.open(url)
        return None, "default"
    except Exception:
        return None, "none"


def _open_existing(url: str, args) -> None:
    if getattr(args, "headless", False) or getattr(args, "browser", "auto") == "none":
        print(url, flush=True)
        return
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Istanza singola / health / dialog
# ---------------------------------------------------------------------------


def _existing_instance(paths: AppPaths) -> Optional[SessionInfo]:
    try:
        with open(paths.instance_path, "r", encoding="utf-8") as handle:
            info = SessionInfo.from_dict(json.load(handle))
    except (OSError, ValueError, TypeError):
        return None
    if not info.pid or not _pid_alive(info.pid):
        _clear_instance(paths)
        return None
    if not info.port or not _health_ok(info.port, timeout=1.5):
        return None
    return info


def _write_instance(paths: AppPaths, session: SessionInfo) -> None:
    try:
        os.makedirs(os.path.dirname(paths.instance_path), exist_ok=True)
        tmp = paths.instance_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(session.to_dict(), handle, indent=2)
        os.replace(tmp, paths.instance_path)
    except OSError:
        pass


def _clear_instance(paths: AppPaths) -> None:
    try:
        os.remove(paths.instance_path)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _health_ok(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/api/health" % port, timeout=timeout
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("status") == "ok"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait_health(port: int, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health_ok(port, timeout=1.0):
            return True
        time.sleep(0.15)
    return False


def _fatal_dialog(title: str, text: str, log_path: str, args) -> None:
    if getattr(args, "headless", False):
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            title,
            "%s\n\nI dettagli sono nel log:\n%s" % (text.strip().splitlines()[-1], log_path),
        )
        root.destroy()
    except Exception:
        pass
