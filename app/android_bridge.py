"""Ponte fra RVC Portable (PC) e l'app Android mini-DAW tramite una cartella Dropbox.

L'app Android carica i file in ``<shared_dir>/AudioIn``, scrive ``config.json`` con i
parametri scelti e attende ``<shared_dir>/AudioOut/<stesso nome>.wav``. Il PC, con il
client Dropbox desktop, vede la cartella sincronizzata come una normale cartella locale:
questo modulo prepara la struttura, genera ``modelli.txt``, applica il config remoto e
tiene sincronizzati i parametri senza API OAuth.

Nessuna chiamata di rete: tutto passa dal filesystem locale sincronizzato da Dropbox.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, List, Optional

from .core import model_scan
from .settings import SettingsManager

LOGGER = logging.getLogger("rvc.android")

DEFAULT_SHARED_NAME = "TestRVC"
DEFAULT_INPUT_SUBDIR = "AudioIn"
DEFAULT_OUTPUT_SUBDIR = "AudioOut"
DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_MODELS_NAME = "modelli.txt"
DEFAULT_STATUS_NAME = "status.json"
F0_METHODS = ("rmvpe", "harvest", "crepe", "pm")
REMOTE_PREFIX = "/" + DEFAULT_SHARED_NAME

MODELS_HEADER = (
    "# modelli.txt - generato da RVC Portable\n"
    "# formato: Nome visualizzato | percorso .pth sul PC | percorso .index sul PC\n"
    "# Righe che iniziano con # vengono ignorate dall'app Android.\n"
)


class AndroidBridgeError(Exception):
    """Errore del ponte Android con messaggio azionabile."""

    def __init__(self, message: str, code: str = "android_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# Rilevamento Dropbox e percorsi
# ---------------------------------------------------------------------------


def _home() -> str:
    return os.path.expanduser("~")


def _clean_path(value: Any) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    return os.path.normpath(os.path.expanduser(text))


def _dropbox_info_files() -> List[str]:
    candidates: List[str] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.path.join(
            _home(), "AppData", "Local"
        )
        candidates.append(os.path.join(local, "Dropbox", "info.json"))
    candidates.append(os.path.join(_home(), ".dropbox", "info.json"))
    candidates.append(os.path.join(_home(), ".dropbox-dist", "info.json"))
    return candidates


def _roots_from_info_json() -> List[Dict[str, str]]:
    roots: List[Dict[str, str]] = []
    for info_path in _dropbox_info_files():
        if not os.path.isfile(info_path):
            continue
        try:
            with open(info_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("personal", "business", "team"):
            entry = data.get(key)
            if not isinstance(entry, dict):
                continue
            path = _clean_path(entry.get("path") or "")
            if path:
                roots.append(
                    {
                        "path": path,
                        "label": str(entry.get("display_name") or key.title()),
                        "source": "dropbox-info",
                    }
                )
    return roots


def detect_dropbox_roots() -> List[Dict[str, Any]]:
    """Cartelle Dropbox locali trovate (info.json + percorsi standard), deduplicate."""
    collected: List[Dict[str, Any]] = []

    def add(path: str, label: str, source: str) -> None:
        path = _clean_path(path)
        if not path or not os.path.isdir(path):
            return
        key = os.path.normcase(path)
        if any(os.path.normcase(item["path"]) == key for item in collected):
            return
        shared = os.path.join(path, DEFAULT_SHARED_NAME)
        collected.append(
            {
                "path": path,
                "label": label or os.path.basename(path),
                "source": source,
                "shared_dir": shared,
                "has_shared": os.path.isdir(shared),
                "has_audio_in": os.path.isdir(os.path.join(shared, DEFAULT_INPUT_SUBDIR)),
            }
        )

    for item in _roots_from_info_json():
        add(item["path"], item["label"], item["source"])

    for env_name in ("RVC_DROPBOX_HOME", "DROPBOX_HOME"):
        value = os.environ.get(env_name)
        if value:
            add(value, "Dropbox (%s)" % env_name, "env")

    home = _home()
    for name in (
        "Dropbox",
        "Dropbox (Personal)",
        "Dropbox (Business)",
        "Dropbox (Team)",
        "Dropbox Personale",
    ):
        add(os.path.join(home, name), name, "standard")
    return collected


def suggest_shared_dir() -> str:
    """Miglior cartella condivisa proposta: Dropbox/TestRVC se esiste, altrimenti la prima."""
    roots = detect_dropbox_roots()
    for item in roots:
        if item.get("has_shared"):
            return item["shared_dir"]
    if roots:
        return roots[0]["shared_dir"]
    return ""


def shared_paths(shared_dir: str, android=None) -> Dict[str, str]:
    """Percorsi locali della cartella condivisa (AudioIn/AudioOut/config/modelli)."""
    shared = _clean_path(shared_dir)
    input_subdir = getattr(android, "input_subdir", DEFAULT_INPUT_SUBDIR) or DEFAULT_INPUT_SUBDIR
    output_subdir = (
        getattr(android, "output_subdir", DEFAULT_OUTPUT_SUBDIR) or DEFAULT_OUTPUT_SUBDIR
    )
    config_name = getattr(android, "config_name", DEFAULT_CONFIG_NAME) or DEFAULT_CONFIG_NAME
    models_name = getattr(android, "models_name", DEFAULT_MODELS_NAME) or DEFAULT_MODELS_NAME
    status_name = getattr(android, "status_name", DEFAULT_STATUS_NAME) or DEFAULT_STATUS_NAME
    return {
        "shared_dir": shared,
        "input_dir": _join_subdir(shared, input_subdir),
        "output_dir": _join_subdir(shared, output_subdir),
        "config_path": os.path.join(shared, config_name) if shared else "",
        "models_path": os.path.join(shared, models_name) if shared else "",
        "status_path": os.path.join(shared, status_name) if shared else "",
    }


def _join_subdir(shared: str, subdir: str) -> str:
    parts = [part for part in str(subdir or "").replace("\\", "/").split("/") if part]
    return os.path.join(shared, *parts) if shared else ""


def remote_dir_for(kind: str, android=None) -> str:
    subdir = (
        getattr(android, "input_subdir", DEFAULT_INPUT_SUBDIR)
        if kind == "input"
        else getattr(android, "output_subdir", DEFAULT_OUTPUT_SUBDIR)
    )
    return "%s/%s" % (REMOTE_PREFIX, str(subdir).strip("/"))


def ensure_shared_dirs(paths: Dict[str, str]) -> List[str]:
    if not paths.get("shared_dir"):
        raise AndroidBridgeError(
            "Cartella condivisa non configurata: scegli la cartella Dropbox/TestRVC",
            "android_not_configured",
        )
    created: List[str] = []
    for key in ("shared_dir", "input_dir", "output_dir"):
        path = paths.get(key) or ""
        if path and not os.path.isdir(path):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                raise AndroidBridgeError(
                    "Impossibile creare %s: %s" % (path, exc), "android_write_failed"
                ) from exc
            created.append(path)
    return created


# ---------------------------------------------------------------------------
# config.json condiviso (compatibile con l'app Android)
# ---------------------------------------------------------------------------


def hybrid_config(settings) -> Dict[str, Any]:
    """Config v3 completa + chiavi piatte che l'app Android legge.

    Android usa ``pitch``, ``method``, ``protect``, ``index_rate``, ``model_path`` e
    ``index_path`` al livello superiore; le chiavi annidate servono al PC.
    """
    data = settings.public_dict()
    android = settings.android
    audio = settings.audio
    flat = {
        "input_dir": remote_dir_for("input", android),
        "output_dir": remote_dir_for("output", android),
        "model_path": audio.model_path,
        "index_path": audio.index_path,
        "pitch": audio.pitch,
        "method": audio.method,
        "protect": audio.protect,
        "index_rate": audio.index_rate,
        "model_version": audio.model_version,
        "output_format": audio.output_format,
    }
    data.update(flat)
    data["android_bridge"] = {
        "app": "rvc-portable-android",
        "format": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return data


def _replace_with_retry(source: str, destination: str, attempts: int = 8) -> None:
    """`os.replace` con retry: il client Dropbox può tenere il file brevemente occupato."""
    last_error: Optional[OSError] = None
    for index in range(attempts):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            last_error = exc
            if index == attempts - 1:
                break
            time.sleep(0.2 * (index + 1))
    if last_error is not None:
        raise last_error


def _write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = "%s.tmp-%d-%d" % (path, os.getpid(), int(time.time() * 1000) % 100000)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def write_hybrid_config(path: str, settings) -> Dict[str, Any]:
    data = hybrid_config(settings)
    write_json_atomic(path, data)
    return data


def read_json_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# modelli.txt
# ---------------------------------------------------------------------------


def write_models_file(path: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Scrive ``modelli.txt`` nel formato letto dall'app Android.

    In caso di nomi duplicati, la variante con indice viene elencata per prima (nome senza
    suffisso), così il telefono propone subito la versione completa.
    """
    if not path:
        raise AndroidBridgeError("Percorso modelli.txt non configurato")
    ordered = sorted(
        [entry for entry in (entries or []) if isinstance(entry, dict)],
        key=lambda entry: (
            str(entry.get("name") or "").lower(),
            not bool(entry.get("index_path")),
        ),
    )
    lines = [MODELS_HEADER.rstrip("\n")]
    used: Dict[str, int] = {}
    written = 0
    for entry in ordered:
        model_path = _clean_path(entry.get("path") or entry.get("model_path") or "")
        if not model_path:
            continue
        base = str(entry.get("name") or os.path.splitext(os.path.basename(model_path))[0]).strip()
        base = base or os.path.splitext(os.path.basename(model_path))[0]
        key = base.lower()
        used[key] = used.get(key, 0) + 1
        display = base if used[key] == 1 else "%s (%d)" % (base, used[key])
        index_path = _clean_path(entry.get("index_path") or "")
        lines.append("%s | %s | %s" % (display, model_path, index_path))
        written += 1
    _write_text_atomic(path, "\n".join(lines) + "\n")
    return {"count": written, "path": path}


def read_models_count(path: str) -> int:
    count = 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if text and not text.startswith("#"):
                    count += 1
    except OSError:
        return 0
    return count


FLAT_KEYS = (
    "input_dir",
    "output_dir",
    "model_path",
    "index_path",
    "pitch",
    "method",
    "protect",
    "index_rate",
    "model_version",
    "output_format",
)


def _flat_view(data: Dict[str, Any]) -> Dict[str, Any]:
    """Solo le chiavi che l'app Android legge, per confrontare due config."""
    return {key: data.get(key) for key in FLAT_KEYS if key in data}


def _needs_hybrid_rewrite(current: Dict[str, Any], desired: Dict[str, Any]) -> bool:
    """True se il config appena letto va riscritto in forma ibrida.

    Se il file è già ibrido/v3 non si tocca; se è il config piatto del telefono si riscrive
    solo quando i valori differiscono da quelli appena applicati (meno scritture = meno
    copie in conflitto con la sincronizzazione Dropbox).
    """
    if "audio" in current:
        return False
    keys = [key for key in FLAT_KEYS if key in current]
    if not keys:
        return True
    return any(current.get(key) != desired.get(key) for key in keys)


def cleanup_stale_temps(directory: str, keep_seconds: int = 600) -> List[str]:
    """Rimuove i file temporanei rimasti da scritture interrotte (`.tmp-*`)."""
    removed: List[str] = []
    if not directory or not os.path.isdir(directory):
        return removed
    now = time.time()
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return removed
    for entry in entries:
        name = entry.name
        if ".tmp-" not in name or not entry.is_file():
            continue
        try:
            if now - entry.stat().st_mtime < keep_seconds:
                continue
            os.remove(entry.path)
            removed.append(entry.path)
        except OSError:
            continue
    return removed


# ---------------------------------------------------------------------------
# Applicazione del config remoto
# ---------------------------------------------------------------------------


def _map_remote_dir(value: str, settings, android, kind: str) -> str:
    text = _clean_path(value)
    if not text:
        return ""
    if os.path.isdir(text):
        return text
    shared = _clean_path(android.shared_dir)
    if not shared:
        return ""
    normalized = str(value or "").strip().replace("\\", "/").rstrip("/")
    expected = remote_dir_for(kind, android).lower()
    sub = (
        android.input_subdir if kind == "input" else android.output_subdir
    ).strip("/").lower()
    base = normalized.rsplit("/", 1)[-1].lower() if normalized else ""
    if (
        normalized.lower() == expected
        or normalized.lower().endswith("/" + expected.lstrip("/"))
        or normalized.lower().endswith("/" + sub)
        or base == sub.rsplit("/", 1)[-1]
    ):
        paths = shared_paths(shared, android)
        target = paths["input_dir"] if kind == "input" else paths["output_dir"]
        try:
            os.makedirs(target, exist_ok=True)
        except OSError:
            return ""
        return target
    return ""


def apply_payload(manager: SettingsManager, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Applica un config.json: completo (v3) oppure piatto (formato app Android)."""
    if not isinstance(payload, dict):
        raise AndroidBridgeError("config.json non valido: atteso un oggetto JSON")
    settings = manager.settings
    if "audio" in payload or "schema_version" in payload:
        try:
            manager.import_dict(payload)
        except Exception as exc:  # pydantic/validazione
            raise AndroidBridgeError(
                "config.json v3 non valido: %s" % exc, "android_config_invalid"
            ) from exc
        return {
            "mode": "full",
            "applied": ["settings"],
            "skipped": [],
            "settings": manager.settings.public_dict(),
        }

    android = settings.android
    applied: List[str] = []
    skipped: List[str] = []
    patch: Dict[str, Any] = {}

    def number(key: str, low: float, high: float, integer: bool = False) -> None:
        if key not in payload or payload.get(key) in (None, ""):
            return
        try:
            value = float(payload[key])
        except (TypeError, ValueError):
            skipped.append(key)
            return
        value = max(low, min(high, value))
        patch[key] = int(round(value)) if integer else round(value, 4)
        applied.append(key)

    number("pitch", -24, 24, integer=True)
    number("protect", 0.0, 0.5)
    number("index_rate", 0.0, 1.0)

    method = str(payload.get("method") or "").strip().lower()
    if method:
        if method in F0_METHODS:
            patch["method"] = method
            applied.append("method")
        else:
            skipped.append("method")

    version = str(payload.get("model_version") or "").strip().lower()
    if version in ("v1", "v2"):
        patch["model_version"] = version
        applied.append("model_version")

    for key in ("model_path", "index_path"):
        if key not in payload or payload.get(key) in (None, ""):
            continue
        path = _clean_path(payload[key])
        if path and os.path.isfile(path):
            patch[key] = path
            applied.append(key)
        else:
            skipped.append(key)

    for key, kind in (("input_dir", "input"), ("output_dir", "output")):
        if key not in payload or payload.get(key) in (None, ""):
            continue
        mapped = _map_remote_dir(payload[key], settings, android, kind)
        if mapped:
            patch[key] = mapped
            applied.append(key)
        else:
            skipped.append(key)

    if patch:
        try:
            manager.apply_patch({"audio": patch})
        except Exception as exc:
            raise AndroidBridgeError(
                "config.json Android non applicabile: %s" % exc,
                "android_config_invalid",
            ) from exc
    return {
        "mode": "android",
        "applied": applied,
        "skipped": skipped,
        "settings": manager.settings.public_dict(),
    }


def import_shared_config(manager: SettingsManager) -> Dict[str, Any]:
    android = manager.settings.android
    paths = shared_paths(android.shared_dir, android)
    payload = read_json_file(paths["config_path"])
    if payload is None:
        raise AndroidBridgeError(
            "config.json non trovato o non valido in %s" % paths["config_path"],
            "android_config_missing",
        )
    return apply_payload(manager, payload)


def export_shared_config(manager: SettingsManager) -> Dict[str, Any]:
    """Scrive il config ibrido nella cartella condivisa (dopo un salvataggio del PC)."""
    android = manager.settings.android
    if not android.enabled or not android.shared_dir:
        return {"written": False, "reason": "android_off"}
    paths = shared_paths(android.shared_dir, android)
    try:
        ensure_shared_dirs(paths)
        cleanup_stale_temps(paths["shared_dir"])
        write_hybrid_config(paths["config_path"], manager.settings)
    except (OSError, AndroidBridgeError) as exc:
        return {"written": False, "reason": str(exc), "path": paths["config_path"]}
    return {"written": True, "path": paths["config_path"]}


def maybe_export_shared(manager: SettingsManager) -> None:
    """Best-effort: non deve mai far fallire un salvataggio impostazioni."""
    try:
        result = export_shared_config(manager)
    except Exception:  # pragma: no cover - difensivo
        LOGGER.exception("export config condivisa fallito")
        return
    if result.get("written"):
        LOGGER.info("config condivisa aggiornata: %s", result.get("path"))


# ---------------------------------------------------------------------------
# Sincronizzazione e preparazione
# ---------------------------------------------------------------------------


def _roots_for_scan(manager: SettingsManager, app_paths) -> List[str]:
    roots: List[str] = []
    models_dir = getattr(app_paths, "models_dir", "") if app_paths is not None else ""
    if models_dir:
        roots.append(models_dir)
    roots.extend(manager.settings.audio.extra_model_dirs or [])
    return [root for root in roots if root]


def scan_entries(manager: SettingsManager, app_paths=None) -> Dict[str, Any]:
    roots = _roots_for_scan(manager, app_paths)
    if not roots:
        return {"roots": [], "models": [], "warnings": ["nessuna cartella modelli"]}
    return model_scan.scan_models(
        roots, default_index_hint=str(manager.settings.audio.index_path or "")
    )


def sync_shared(manager: SettingsManager, app_paths=None) -> Dict[str, Any]:
    """Crea le cartelle, scrive modelli.txt e il config.json condiviso."""
    android = manager.settings.android
    paths = shared_paths(android.shared_dir, android)
    created = ensure_shared_dirs(paths)
    cleanup_stale_temps(paths["shared_dir"])
    scan = scan_entries(manager, app_paths)
    entries = list(scan.get("models") or [])
    models_info = write_models_file(paths["models_path"], entries)
    write_hybrid_config(paths["config_path"], manager.settings)
    return {
        "shared_dir": paths["shared_dir"],
        "paths": paths,
        "created": created,
        "models": models_info["count"],
        "models_path": paths["models_path"],
        "config_path": paths["config_path"],
        "scan_roots": list(scan.get("roots") or []),
        "warnings": list(scan.get("warnings") or []),
    }


def prepare(manager: SettingsManager, app_paths=None, shared_dir: str = "", watcher=None) -> Dict[str, Any]:
    """Preset completo: cartella condivisa, AudioIn/AudioOut, config e modelli."""
    shared = _clean_path(shared_dir) or suggest_shared_dir()
    if not shared:
        raise AndroidBridgeError(
            "Dropbox non trovato: scegli a mano la cartella condivisa (es. Dropbox/TestRVC)",
            "android_dropbox_missing",
        )
    android = manager.settings.android
    paths = shared_paths(shared, android)
    ensure_shared_dirs(paths)
    scan = scan_entries(manager, app_paths)
    entries = list(scan.get("models") or [])

    patch: Dict[str, Any] = {
        "android": {"enabled": True, "shared_dir": shared},
        "audio": {
            "input_dir": paths["input_dir"],
            "output_dir": paths["output_dir"],
            "output_format": "wav",
        },
        "cloud": {"local_path": paths["config_path"], "hot_reload": True},
        "monitor": {"ignore_output_dir": True, "enabled_on_start": True},
    }
    if not manager.settings.audio.model_path and entries:
        first = entries[0]
        if first.get("path"):
            patch["audio"]["model_path"] = first["path"]
            patch["audio"]["index_path"] = first.get("index_path") or ""
    manager.apply_patch(patch)

    summary = sync_shared(manager, app_paths)
    started = False
    if watcher is not None:
        try:
            watcher.start(
                summary["paths"]["input_dir"],
                process_existing=bool(manager.settings.monitor.process_existing),
            )
            started = True
        except Exception as exc:  # il preset non deve fallire per il watcher
            LOGGER.warning("android: watcher non avviato: %s", exc)
    summary["watcher_started"] = started
    summary["settings"] = manager.settings.public_dict()
    return summary


def status(manager: SettingsManager, app_paths=None, config_sync=None) -> Dict[str, Any]:
    settings = manager.settings
    android = settings.android
    paths = shared_paths(android.shared_dir, android)
    roots = detect_dropbox_roots()
    models_count = read_models_count(paths["models_path"]) if paths["models_path"] else 0
    info = {
        "enabled": bool(android.enabled),
        "shared_dir": android.shared_dir,
        "suggested_shared_dir": suggest_shared_dir(),
        "roots": roots,
        "paths": paths,
        "input_dir": paths["input_dir"],
        "output_dir": paths["output_dir"],
        "config_exists": bool(paths["config_path"] and os.path.isfile(paths["config_path"])),
        "models_exists": bool(paths["models_path"] and os.path.isfile(paths["models_path"])),
        "status_exists": bool(paths["status_path"] and os.path.isfile(paths["status_path"])),
        "models_count": models_count,
        "same_name_output": bool(android.same_name_output),
        "apply_remote_config": bool(android.apply_remote_config),
        "cloud_hot_reload": bool(settings.cloud.hot_reload),
        "scan_roots": _roots_for_scan(manager, app_paths),
    }
    if config_sync is not None:
        try:
            info["config_sync"] = config_sync.status()
        except Exception:  # pragma: no cover
            info["config_sync"] = {}
    try:
        payload = read_status(manager)
        if payload:
            info["pc_status"] = payload
    except Exception:  # pragma: no cover
        pass
    return info


# ---------------------------------------------------------------------------
# Hot reload del config condiviso
# ---------------------------------------------------------------------------


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ConfigSync:
    """Osserva ``cloud.local_path`` e applica i cambi di configurazione.

    Funziona sia con il config v3 completo (sincronizzazione PC) sia con il config
    piatto scritto dall'app Android. Dopo aver applicato un config Android riscrive
    il file in forma ibrida (v3 + chiavi piatte) per tenerlo coerente per entrambi.
    """

    def __init__(self, manager: SettingsManager, bus=None, interval_s: float = 2.0) -> None:
        self.manager = manager
        self.bus = bus
        self.interval_s = max(1.0, float(interval_s or 2.0))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._path = ""
        self._last_hash = ""
        self._last_applied: Optional[Dict[str, Any]] = None
        self._last_error = ""
        self._last_check = 0.0
        self._applied_count = 0

    # ------------------------------------------------------------------ api
    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="rvc-config-sync", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._thread = None

    def status(self) -> Dict[str, Any]:
        return {
            "running": bool(self._thread is not None and self._thread.is_alive()),
            "path": self._path,
            "last_check": round(self._last_check, 3),
            "last_applied": self._last_applied,
            "last_error": self._last_error,
            "applied_count": self._applied_count,
        }

    def apply_now(self) -> Dict[str, Any]:
        """Applica subito il file config (utile per il pulsante "Applica config")."""
        return self._check(force=True) or {
            "applied": [],
            "skipped": [],
            "mode": "none",
        }

    # -------------------------------------------------------------- internals
    def _resolve_path(self) -> str:
        settings = self.manager.settings
        local = str(settings.cloud.local_path or "").strip()
        if local:
            return os.path.abspath(os.path.expanduser(local))
        android = settings.android
        if android.enabled and android.shared_dir:
            return shared_paths(android.shared_dir, android)["config_path"]
        return ""

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                path = self._resolve_path()
                if path:
                    if path != self._path:
                        with self._lock:
                            self._path = path
                            self._last_hash = ""
                    self._check(path=path)
            except Exception as exc:  # pragma: no cover - difensivo
                self._last_error = str(exc)
                LOGGER.warning("config sync: %s", exc)
            self._stop.wait(self.interval_s)

    def _check(self, path: Optional[str] = None, force: bool = False) -> Optional[Dict[str, Any]]:
        target = path or self._path or self._resolve_path()
        if not target:
            return None
        if not os.path.isfile(target):
            self._last_error = ""
            return None
        try:
            with open(target, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            self._last_error = "config.json non leggibile: %s" % exc
            return None
        digest = _hash_bytes(raw)
        if not force and digest == self._last_hash:
            self._last_check = time.time()
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._last_hash = digest
            self._last_error = "config.json non valido: %s" % exc
            return None
        if not isinstance(payload, dict):
            self._last_hash = digest
            self._last_error = "config.json non valido: atteso un oggetto"
            return None
        try:
            result = apply_payload(self.manager, payload)
        except AndroidBridgeError as exc:
            self._last_hash = digest
            self._last_error = exc.message
            return None
        self._last_error = ""
        self._last_applied = result
        self._applied_count += 1
        self._last_check = time.time()
        if result.get("mode") == "android":
            # Riscrive la forma ibrida solo se serve davvero: meno scritture = meno
            # copie in conflitto quando Dropbox sincronizza in parallelo.
            current = payload if isinstance(payload, dict) else {}
            desired = hybrid_config(self.manager.settings)
            if _needs_hybrid_rewrite(current, desired):
                try:
                    write_hybrid_config(target, self.manager.settings)
                    cleanup_stale_temps(os.path.dirname(target))
                    with open(target, "rb") as handle:
                        digest = _hash_bytes(handle.read())
                except OSError:
                    pass
        self._last_hash = digest
        if self.bus is not None:
            try:
                self.bus.publish(
                    "config",
                    {
                        "source": "android" if result.get("mode") == "android" else "cloud",
                        "applied": result.get("applied", []),
                        "skipped": result.get("skipped", []),
                        "path": target,
                    },
                )
            except Exception:  # pragma: no cover
                LOGGER.exception("config sync: pubblicazione evento fallita")
        LOGGER.info(
            "config sincronizzata da %s: %s", target, ", ".join(result.get("applied") or [])
        )
        return result

# ---------------------------------------------------------------------------
# Heartbeat di stato per l'app Android (controllo remoto dal telefono)
# ---------------------------------------------------------------------------

STATUS_SCHEMA = 1


def _jsonable(value: Any, depth: int = 0) -> Any:
    """Converte in JSON strutture anche annidate (dataclass, enum, Path)."""
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return {key: _jsonable(item, depth + 1) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item, depth + 1) for item in value]
    return str(value)


class StatusPublisher:
    """Scrive ``status.json`` nella cartella condivisa: il telefono vede il PC.

    Nessuna rete in ingresso: il telefono legge il file sincronizzato da Dropbox e
    mostra online/offline, motore, coda, modello e ultima config applicata.
    """

    def __init__(
        self,
        manager: SettingsManager,
        providers: Optional[Dict[str, Callable[[], Any]]] = None,
        interval_s: float = 5.0,
    ) -> None:
        self.manager = manager
        self.providers = providers or {}
        self.interval_s = max(2.0, float(interval_s or 5.0))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_error = ""
        self._last_written = 0.0
        self._writes = 0

    # ------------------------------------------------------------------ api
    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="rvc-android-status", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._thread = None

    def status(self) -> Dict[str, Any]:
        return {
            "running": bool(self._thread is not None and self._thread.is_alive()),
            "interval_s": self.interval_s,
            "writes": self._writes,
            "last_written": round(self._last_written, 3),
            "last_error": self._last_error,
        }

    def build_status(self) -> Dict[str, Any]:
        now = time.time()
        data: Dict[str, Any] = {
            "schema": STATUS_SCHEMA,
            "app": "rvc-portable",
            "timestamp": round(now, 3),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "providers": {},
        }
        for name, provider in self.providers.items():
            try:
                raw = provider()
                if name == "config" and isinstance(raw, dict):
                    # Non includere l'intera configurazione: il telefono mostra solo
                    # lo stato sintetico (il payload deve restare piccolo per Dropbox).
                    last = raw.get("last_applied") or {}
                    raw = {
                        "running": raw.get("running"),
                        "path": raw.get("path"),
                        "last_check": raw.get("last_check"),
                        "last_error": raw.get("last_error", ""),
                        "applied_count": raw.get("applied_count", 0),
                        "mode": last.get("mode", "") if isinstance(last, dict) else "",
                        "applied": len(last.get("applied") or []) if isinstance(last, dict) else 0,
                    }
                data["providers"][name] = _jsonable(raw)
            except Exception as exc:  # pragma: no cover - difensivo
                data["providers"][name] = {"error": str(exc)}
        settings = self.manager.settings
        audio = settings.audio
        data["audio"] = {
            "model_path": audio.model_path,
            "index_path": audio.index_path,
            "pitch": audio.pitch,
            "method": audio.method,
            "protect": audio.protect,
            "index_rate": audio.index_rate,
            "model_version": audio.model_version,
            "output_format": audio.output_format,
        }
        data["android"] = {
            "enabled": bool(settings.android.enabled),
            "shared_dir": settings.android.shared_dir,
        }
        return data

    def publish_once(self) -> Optional[Dict[str, Any]]:
        settings = self.manager.settings
        if not settings.android.enabled or not settings.android.shared_dir:
            return None
        paths = shared_paths(settings.android.shared_dir, settings.android)
        path = paths.get("status_path") or ""
        if not path:
            return None
        data = self.build_status()
        try:
            write_json_atomic(path, data)
        except OSError as exc:
            self._last_error = str(exc)
            LOGGER.warning("status.json non scrivibile: %s", exc)
            return None
        cleanup_stale_temps(paths["shared_dir"])
        self._last_error = ""
        self._last_written = time.time()
        self._writes += 1
        return data

    # -------------------------------------------------------------- internals
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.publish_once()
            except Exception as exc:  # pragma: no cover - difensivo
                self._last_error = str(exc)
                LOGGER.warning("status publisher: %s", exc)
            self._stop.wait(self.interval_s)


def read_status(manager: SettingsManager) -> Optional[Dict[str, Any]]:
    """Legge ``status.json`` dalla cartella condivisa (se presente)."""
    settings = manager.settings
    if not settings.android.shared_dir:
        return None
    paths = shared_paths(settings.android.shared_dir, settings.android)
    return read_json_file(paths.get("status_path") or "")
