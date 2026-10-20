"""Configurazione applicativa (schema v3) con migrazione dallo schema v2 piatto.

Caratteristiche:
- modelli Pydantic v1 (compatibili con Python 3.9 e con il runtime 3.9.13);
- scrittura **atomica** (tmp + fsync + os.replace) con backup ``.bak``;
- migrazione automatica dal vecchio ``config.json`` piatto, con warning espliciti;
- validazione di campi e percorsi, senza mai modificare i file dell'utente.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, validator

from .paths import AppPaths

SCHEMA_VERSION = 3
F0_METHODS = ("rmvpe", "harvest", "crepe", "pm")
OUTPUT_FORMATS = ("wav", "flac")
THEMES = ("dark", "light", "system")
WATCH_MODES = ("auto", "native", "polling")
DEVICE_VALUES = ("auto", "cpu", "cuda", "mps")

DEFAULT_IGNORE_GLOBS = ["*.tmp", "*.part", "*.crdownload", "~$*", ".*"]


def _clean_path(value: str) -> str:
    if not value:
        return ""
    return os.path.normpath(os.path.expanduser(value.strip().strip('"')))


class AudioSettings(BaseModel):
    input_dir: str = ""
    output_dir: str = ""
    model_path: str = ""
    index_path: str = ""
    extra_model_dirs: List[str] = Field(
        default_factory=list,
        description="cartelle aggiuntive in cui cercare modelli (es. Dropbox/Modelli)",
    )
    model_version: str = Field("v2", description="v1 oppure v2")
    pitch: int = Field(0, ge=-24, le=24)
    method: str = "rmvpe"
    protect: float = Field(0.33, ge=0.0, le=0.5)
    index_rate: float = Field(0.3, ge=0.0, le=1.0)
    filter_radius: int = Field(3, ge=0, le=7)
    rms_mix_rate: float = Field(0.25, ge=0.0, le=1.0)
    resample_sr: int = Field(0, ge=0, le=48000)
    output_format: str = "wav"

    class Config:
        extra = "ignore"

    @validator("input_dir", "output_dir", "model_path", "index_path", pre=True)
    def _paths(cls, value):  # noqa: N805
        return _clean_path(value or "")

    @validator("extra_model_dirs", pre=True)
    def _extra_dirs(cls, value):  # noqa: N805
        if not value:
            return []
        if isinstance(value, str):
            value = [value]
        cleaned: List[str] = []
        seen = set()
        for item in value:
            path = _clean_path(str(item or ""))
            if not path:
                continue
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(path)
        return cleaned

    @validator("method")
    def _method(cls, value):  # noqa: N805
        value = (value or "rmvpe").strip().lower()
        if value not in F0_METHODS:
            raise ValueError("metodo pitch non supportato: %s" % value)
        return value

    @validator("model_version")
    def _version(cls, value):  # noqa: N805
        value = (value or "v2").strip().lower()
        if value not in ("v1", "v2"):
            raise ValueError("versione modello non valida: %s" % value)
        return value

    @validator("output_format")
    def _format(cls, value):  # noqa: N805
        value = (value or "wav").strip().lower()
        if value not in OUTPUT_FORMATS:
            raise ValueError("formato output non valido: %s" % value)
        return value


class EngineSettings(BaseModel):
    device: str = "auto"
    warm_model: bool = True
    idle_unload_minutes: int = Field(15, ge=0, le=600)
    max_concurrency: int = Field(1, ge=1, le=1, description="un solo job GPU")

    class Config:
        extra = "ignore"

    @validator("device")
    def _device(cls, value):  # noqa: N805
        value = (value or "auto").strip().lower()
        if value in ("cuda:", "cuda"):
            return "cuda:0"
        if value in ("cpu:",):
            return "cpu"
        if value == "dml:0":
            raise ValueError(
                "DirectML non e' supportato dal motore rvc-python; usa auto/cpu/cuda"
            )
        if value.startswith("cuda:") and value[5:].isdigit():
            return value
        if value not in DEVICE_VALUES:
            raise ValueError("device non valido: %s" % value)
        return value


class MonitorSettings(BaseModel):
    enabled_on_start: bool = False
    process_existing: bool = False
    watch_mode: str = "auto"
    poll_interval_s: float = Field(2.0, ge=0.5, le=30.0)
    stability_ms: int = Field(1500, ge=0, le=10000)
    ignore_globs: List[str] = Field(default_factory=lambda: list(DEFAULT_IGNORE_GLOBS))
    ignore_output_dir: bool = True

    class Config:
        extra = "ignore"

    @validator("watch_mode")
    def _mode(cls, value):  # noqa: N805
        value = (value or "auto").strip().lower()
        if value not in WATCH_MODES:
            raise ValueError("modalita' di watch non valida: %s" % value)
        return value


class DropboxSettings(BaseModel):
    app_key: str = ""
    remote_path: str = "/NLTools/RVC/config.json"

    class Config:
        extra = "ignore"

    @validator("app_key", pre=True)
    def _key(cls, value):  # noqa: N805
        return (value or "").strip()

    @validator("remote_path")
    def _remote(cls, value):  # noqa: N805
        value = (value or "/NLTools/RVC/config.json").strip()
        if not value.startswith("/"):
            value = "/" + value
        return value


class CloudSettings(BaseModel):
    dropbox: DropboxSettings = Field(default_factory=DropboxSettings)
    local_path: str = ""
    hot_reload: bool = False
    poll_interval_s: float = Field(3.0, ge=1.0, le=60.0)

    class Config:
        extra = "ignore"

    @validator("local_path", pre=True)
    def _local(cls, value):  # noqa: N805
        return _clean_path(value or "")


class AndroidSettings(BaseModel):
    """Ponte con l'app Android (mini DAW) tramite una cartella Dropbox sincronizzata.

    L'app Android carica i file in ``<shared_dir>/AudioIn``, scrive il ``config.json``
    con i parametri scelti e attende ``<shared_dir>/AudioOut/<stesso nome>.wav``.
    """

    enabled: bool = False
    shared_dir: str = ""
    input_subdir: str = "AudioIn"
    output_subdir: str = "AudioOut"
    config_name: str = "config.json"
    models_name: str = "modelli.txt"
    status_name: str = "status.json"
    status_heartbeat_s: float = Field(300.0, ge=30.0, le=1800.0)
    apply_remote_config: bool = True
    same_name_output: bool = True

    class Config:
        extra = "ignore"

    @validator("shared_dir", pre=True)
    def _dir(cls, value):  # noqa: N805
        return _clean_path(value or "")

    @validator("input_subdir", "output_subdir", pre=True)
    def _subdir(cls, value):  # noqa: N805
        return _clean_subdir(value, "AudioIn")

    @validator("config_name", "models_name", pre=True)
    def _filename(cls, value):  # noqa: N805
        text = os.path.basename(str(value or "").strip().replace("\\", "/"))
        return text or "config.json"

    @validator("status_name", pre=True)
    def _status_filename(cls, value):  # noqa: N805
        text = os.path.basename(str(value or "").strip().replace("\\", "/"))
        return text or "status.json"


def _clean_subdir(value: Any, default: str) -> str:
    text = str(value or "").strip().replace("\\", "/").strip("/")
    if not text or text in (".", ".."):
        return default
    parts = [part for part in text.split("/") if part not in ("", ".", "..")]
    return "/".join(parts) or default


class UISettings(BaseModel):
    language: str = "it"
    theme: str = "dark"
    last_view: str = "dashboard"
    compact: bool = False

    class Config:
        extra = "ignore"

    @validator("language")
    def _lang(cls, value):  # noqa: N805
        value = (value or "it").strip().lower()[:8]
        return value or "it"

    @validator("theme")
    def _theme(cls, value):  # noqa: N805
        value = (value or "dark").strip().lower()
        return value if value in THEMES else "dark"

    @validator("last_view")
    def _view(cls, value):  # noqa: N805
        value = (value or "dashboard").strip().lower()
        allowed = ("dashboard", "config", "monitor", "models", "cloud", "advanced")
        return value if value in allowed else "dashboard"


class Settings(BaseModel):
    schema_version: int = SCHEMA_VERSION
    audio: AudioSettings = Field(default_factory=AudioSettings)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    android: AndroidSettings = Field(default_factory=AndroidSettings)
    ui: UISettings = Field(default_factory=UISettings)

    class Config:
        extra = "ignore"

    # ------------------------------------------------------------ serializing
    def public_dict(self) -> Dict[str, Any]:
        return json.loads(self.json())

    # -------------------------------------------------------------- validators
    def validate_paths(self) -> List[Dict[str, Any]]:
        """Problemi sui percorsi configurati (non bloccanti per l'avvio)."""
        problems: List[Dict[str, Any]] = []

        def check_file(field: str, value: str, required: bool) -> None:
            if not value:
                if required:
                    problems.append(
                        {"field": field, "reason": "missing", "value": value}
                    )
                return
            if not os.path.isfile(value):
                problems.append(
                    {"field": field, "reason": "not_found", "value": value}
                )

        def check_dir(field: str, value: str, required: bool) -> None:
            if not value:
                if required:
                    problems.append(
                        {"field": field, "reason": "missing", "value": value}
                    )
                return
            if not os.path.isdir(value):
                problems.append(
                    {"field": field, "reason": "not_a_directory", "value": value}
                )

        check_dir("audio.input_dir", self.audio.input_dir, required=True)
        check_dir("audio.output_dir", self.audio.output_dir, required=False)
        check_file("audio.model_path", self.audio.model_path, required=True)
        if self.audio.index_path:
            check_file("audio.index_path", self.audio.index_path, required=False)
        for index, directory in enumerate(self.audio.extra_model_dirs):
            check_dir("audio.extra_model_dirs[%d]" % index, directory, required=False)
        if self.cloud.local_path:
            check_file("cloud.local_path", self.cloud.local_path, required=False)
        if self.android.enabled:
            check_dir("android.shared_dir", self.android.shared_dir, required=True)
        elif self.android.shared_dir:
            check_dir("android.shared_dir", self.android.shared_dir, required=False)
        return problems


# ---------------------------------------------------------------------------
# Migrazione dallo schema v2 (config.json piatto)
# ---------------------------------------------------------------------------

_V2_AUDIO_KEYS = (
    "input_dir",
    "output_dir",
    "model_path",
    "index_path",
    "pitch",
    "method",
    "protect",
    "index_rate",
    "device",
    "language",
)


def _migrate_flat_v2(flat: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    audio: Dict[str, Any] = {}
    for key in (
        "input_dir",
        "output_dir",
        "model_path",
        "index_path",
        "pitch",
        "method",
        "protect",
        "index_rate",
    ):
        if key in flat and flat[key] not in (None, ""):
            audio[key] = flat[key]

    method = str(audio.get("method", "rmvpe")).strip().lower()
    if method == "fcpe":
        audio["method"] = "rmvpe"
        warnings.append("migrazione: metodo 'fcpe' non supportato, impostato 'rmvpe'")

    device = str(flat.get("device", "auto") or "auto").strip().lower()
    if device.startswith("dml"):
        device = "auto"
        warnings.append(
            "migrazione: DirectML non supportato dal motore, device impostato 'auto'"
        )
    engine = {"device": device or "auto"}

    cloud: Dict[str, Any] = {
        "dropbox": {"app_key": str(flat.get("dropbox_app_key", "") or "")},
        "local_path": str(flat.get("cloud_config_path", "") or ""),
        "hot_reload": bool(flat.get("auto_reload_cloud", False)),
    }
    ui = {"language": str(flat.get("language", "it") or "it")}

    migrated = {
        "schema_version": SCHEMA_VERSION,
        "audio": audio,
        "engine": engine,
        "cloud": cloud,
        "ui": ui,
    }
    unknown = sorted(set(flat.keys()) - set(_V2_AUDIO_KEYS) - {
        "cloud_config_path",
        "auto_reload_cloud",
        "dropbox_app_key",
    })
    if unknown:
        warnings.append("migrazione: chiavi ignorate: %s" % ", ".join(unknown))
    return migrated, warnings


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class SettingsError(Exception):
    """Errore di lettura/scrittura della configurazione."""


class SettingsManager:
    """Carica/salva la configurazione in modo atomico e thread-safe."""

    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.settings = Settings()
        self.warnings: List[str] = []
        self._loaded_from: Optional[str] = None

    # ------------------------------------------------------------------ load
    def load(self) -> Settings:
        self.warnings = []
        self._loaded_from = None

        if os.path.isfile(self.paths.config_path):
            data = self._read_json(self.paths.config_path)
            if data is not None:
                self.settings = self._build(data, self.paths.config_path)
                self._loaded_from = self.paths.config_path
                return self.settings

        legacy = self.paths.legacy_config_path
        if os.path.isfile(legacy):
            data = self._read_json(legacy)
            if data is not None:
                migrated, warnings = _migrate_flat_v2(data)
                self.warnings.extend(warnings)
                self.settings = self._build(migrated, legacy)
                self._loaded_from = legacy
                try:
                    self.save()
                    self.warnings.append(
                        "migrazione: configurazione importata da '%s'" % legacy
                    )
                except SettingsError as exc:
                    self.warnings.append("migrazione: salvataggio fallito: %s" % exc)
                return self.settings

        self.settings = Settings()
        return self.settings

    def _build(self, data: Dict[str, Any], source: str) -> Settings:
        if not isinstance(data, dict):
            raise SettingsError("configurazione non valida in %s" % source)
        if "schema_version" not in data and "audio" not in data:
            migrated, warnings = _migrate_flat_v2(data)
            self.warnings.extend(warnings)
            data = migrated
        try:
            return Settings(**data)
        except Exception as exc:  # pydantic.ValidationError
            raise SettingsError("configurazione non valida in %s: %s" % (source, exc))

    def _read_json(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            self.warnings.append(
                "configurazione illeggibile (%s): %s" % (path, exc)
            )
            return None
        if not isinstance(data, dict):
            self.warnings.append("configurazione non valida (%s): atteso oggetto" % path)
            return None
        return data

    # ------------------------------------------------------------------ save
    def save(self, settings: Optional[Settings] = None) -> Settings:
        target = settings or self.settings
        self.settings = target
        path = self.paths.config_path
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        tmp_path = "%s.tmp-%d" % (path, os.getpid())
        payload = json.dumps(
            target.public_dict(), indent=4, ensure_ascii=False, sort_keys=False
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if os.path.isfile(path):
                try:
                    shutil.copyfile(path, self.paths.backup_config_path)
                except OSError:
                    pass
            os.replace(tmp_path, path)
        except OSError as exc:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise SettingsError("impossibile salvare %s: %s" % (path, exc))
        return self.settings

    # ----------------------------------------------------------------- patch
    def apply_patch(self, partial: Dict[str, Any]) -> Settings:
        merged = _deep_merge(self.settings.public_dict(), partial or {})
        merged["schema_version"] = SCHEMA_VERSION
        merged = self._drop_unknown(merged)
        candidate = Settings(**merged)
        self.save(candidate)
        return candidate

    @staticmethod
    def _drop_unknown(data: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in data.items():
            if key in Settings.__fields__:
                cleaned[key] = value
        return cleaned

    # ---------------------------------------------------------- import/export
    def export_dict(self) -> Dict[str, Any]:
        data = self.settings.public_dict()
        data["exported_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return data

    def import_dict(self, data: Dict[str, Any]) -> Settings:
        if not isinstance(data, dict):
            raise SettingsError("import: atteso un oggetto JSON")
        self.warnings = []
        if "schema_version" not in data and "audio" not in data:
            migrated, warnings = _migrate_flat_v2(data)
            self.warnings.extend(warnings)
            data = migrated
        candidate = Settings(**data)
        self.save(candidate)
        return candidate


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
