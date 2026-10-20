"""Risoluzione dei percorsi dell'applicazione.

Regola d'oro: l'app e' *portatile* per default (dati in ``<root>/data``), ma se
la cartella non e' scrivibile (installazione in Program Files, supporto
read-only, ecc.) si ricade nella directory dati utente del sistema operativo.

Nessuna dipendenza esterna: solo stdlib, cosi' il modulo resta importabile su
Python 3.9+ e anche prima che torch/rvc-python siano caricati.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional

APP_DIR_NAME = "NLTools"
APP_DIR_NAME_POSIX = "nltools-rvc"

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def _writable_dir(path: str) -> bool:
    """True se `path` puo' essere creata/scritta (test reale, non solo os.access)."""
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".writetest-", dir=path, delete=True
        ) as handle:
            handle.write(b"ok")
            handle.flush()
        return True
    except OSError:
        return False


def user_data_dir() -> str:
    """Directory dati per-utente, secondo le convenzioni del sistema operativo."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
            r"~\AppData\Local"
        )
        return os.path.join(base, APP_DIR_NAME, "RVC")
    if IS_MACOS:
        return os.path.join(
            os.path.expanduser("~/Library/Application Support"),
            APP_DIR_NAME,
            "RVC",
        )
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_DIR_NAME_POSIX)


def default_app_root() -> str:
    """Radice del progetto: la cartella che contiene ``app/`` e ``web/``."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class AppPaths:
    """Insieme coerente di percorsi usati da backend, launcher e strumenti."""

    app_root: str
    data_dir: str
    portable: bool
    config_file: Optional[str] = None

    # ---------------------------------------------------------------- factory
    @classmethod
    def create(
        cls,
        app_root: Optional[str] = None,
        data_dir: Optional[str] = None,
        prefer_portable: bool = True,
        config_path: Optional[str] = None,
    ) -> "AppPaths":
        root = os.path.abspath(app_root or default_app_root())
        if data_dir:
            chosen = os.path.abspath(data_dir)
            portable = os.path.abspath(chosen).startswith(root + os.sep)
        elif prefer_portable:
            candidate = os.path.join(root, "data")
            if _writable_dir(candidate):
                chosen, portable = candidate, True
            else:
                chosen, portable = user_data_dir(), False
        else:
            chosen, portable = user_data_dir(), False
        config_file = os.path.abspath(config_path) if config_path else None
        if config_file and not data_dir:
            chosen = os.path.dirname(config_file)
            portable = chosen.startswith(root + os.sep)
        paths = cls(
            app_root=root,
            data_dir=chosen,
            portable=portable,
            config_file=config_file,
        )
        paths.ensure()
        return paths

    # ------------------------------------------------------------------- dirs
    def ensure(self) -> None:
        for path in (
            self.data_dir,
            self.state_dir,
            self.logs_dir,
            self.cache_dir,
            self.browser_profile_dir,
        ):
            os.makedirs(path, exist_ok=True)

    @property
    def config_path(self) -> str:
        return self.config_file or os.path.join(self.data_dir, "config.json")

    @property
    def backup_config_path(self) -> str:
        return self.config_path + ".bak"

    @property
    def state_dir(self) -> str:
        return os.path.join(self.data_dir, "state")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.data_dir, "logs")

    @property
    def cache_dir(self) -> str:
        return os.path.join(self.data_dir, "cache")

    @property
    def browser_profile_dir(self) -> str:
        return os.path.join(self.data_dir, "browser")

    @property
    def session_path(self) -> str:
        return os.path.join(self.state_dir, "session.json")

    @property
    def instance_path(self) -> str:
        return os.path.join(self.state_dir, "instance.json")

    @property
    def environment_path(self) -> str:
        return os.path.join(self.state_dir, "environment.json")

    @property
    def dropbox_state_path(self) -> str:
        return os.path.join(self.state_dir, "dropbox.json")

    @property
    def jobs_state_path(self) -> str:
        return os.path.join(self.state_dir, "jobs.jsonl")

    @property
    def processed_state_path(self) -> str:
        return os.path.join(self.state_dir, "processed.json")

    @property
    def app_log_path(self) -> str:
        return os.path.join(self.logs_dir, "app.log")

    @property
    def engine_log_path(self) -> str:
        return os.path.join(self.logs_dir, "engine.log")

    @property
    def stdout_log_path(self) -> str:
        return os.path.join(self.logs_dir, "stdout.log")

    @property
    def web_dir(self) -> str:
        return os.path.join(self.app_root, "web")

    @property
    def locales_dir(self) -> str:
        return os.path.join(self.app_root, "locales")

    @property
    def docs_dir(self) -> str:
        return os.path.join(self.app_root, "docs")

    @property
    def models_dir(self) -> str:
        """Cartella modelli storica: non viene mai modificata dall'app."""
        return os.path.join(self.app_root, "Modelli")

    @property
    def runtime_dir(self) -> str:
        return os.path.join(self.app_root, "runtime")

    @property
    def legacy_config_path(self) -> str:
        return os.path.join(self.app_root, "config.json")

    # --------------------------------------------------------------- runtime
    @property
    def runtime_python(self) -> Optional[str]:
        """Interprete del runtime bundled, se presente."""
        candidates = []
        if IS_WINDOWS:
            candidates.append(os.path.join(self.runtime_dir, "python.exe"))
        else:
            candidates.append(os.path.join(self.runtime_dir, "bin", "python3"))
        candidates.append(os.path.join(self.app_root, ".venv", "bin", "python3"))
        candidates.append(os.path.join(self.app_root, ".venv", "Scripts", "python.exe"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    @property
    def runtime_pythonw(self) -> Optional[str]:
        if IS_WINDOWS:
            candidate = os.path.join(self.runtime_dir, "pythonw.exe")
            if os.path.isfile(candidate):
                return candidate
        return self.runtime_python

    def describe(self) -> dict:
        """Rappresentazione JSON-serializzabile usata da /api/meta e doctor."""
        return {
            "app_root": self.app_root,
            "data_dir": self.data_dir,
            "portable": self.portable,
            "config_path": self.config_path,
            "logs_dir": self.logs_dir,
            "cache_dir": self.cache_dir,
            "models_dir": self.models_dir,
            "runtime_python": self.runtime_python,
            "platform": sys.platform,
        }
