"""Contratto del motore di inferenza e implementazioni di servizio.

- ``Engine``: interfaccia usata da API e job queue.
- ``NullEngine``: motore assente (degraded mode) con messaggio azionabile.
- ``FakeEngine``: motore finto per test veloci, nessun torch richiesto.
"""

from __future__ import annotations

import abc
import math
import os
import struct
import time
import wave
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class EngineStatus:
    available: bool
    code: str = ""
    message: str = ""
    device: str = ""
    requested_device: str = ""
    model_path: str = ""
    index_path: str = ""
    model_version: str = "v2"
    loaded: bool = False
    warm: bool = False
    busy: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InferParams:
    pitch: int = 0
    method: str = "rmvpe"
    protect: float = 0.33
    index_rate: float = 0.3
    filter_radius: int = 3
    rms_mix_rate: float = 0.25
    resample_sr: int = 0
    model_version: str = "v2"
    output_format: str = "wav"

    @classmethod
    def from_audio(cls, audio) -> "InferParams":
        return cls(
            pitch=int(audio.pitch),
            method=str(audio.method),
            protect=float(audio.protect),
            index_rate=float(audio.index_rate),
            filter_radius=int(audio.filter_radius),
            rms_mix_rate=float(audio.rms_mix_rate),
            resample_sr=int(audio.resample_sr),
            model_version=str(audio.model_version),
            output_format=str(audio.output_format),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InferResult:
    ok: bool
    output_path: str = ""
    duration_s: float = 0.0
    sample_rate: int = 0
    elapsed_s: float = 0.0
    error_code: str = ""
    error_message: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EngineError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


LogCallback = Callable[[str], None]
StageCallback = Callable[[str, Optional[float]], None]
CancelEvent = Callable[[], bool]


class Engine(abc.ABC):
    name = "engine"

    @abc.abstractmethod
    def status(self) -> EngineStatus: ...

    @abc.abstractmethod
    def load(
        self,
        model_path: str,
        index_path: str = "",
        version: str = "v2",
        device: str = "auto",
    ) -> None: ...

    @abc.abstractmethod
    def infer(
        self,
        input_path: str,
        output_path: str,
        params: InferParams,
        on_log: Optional[LogCallback] = None,
        on_stage: Optional[StageCallback] = None,
        is_cancelled: Optional[CancelEvent] = None,
    ) -> InferResult: ...

    def cancel(self) -> None:
        """Interruzione cooperativa del job in corso (default: no-op)."""
        return None

    def unload(self) -> None:
        """Rilascia il modello (default: no-op)."""
        return None

    def shutdown(self) -> None:
        """Chiude risorse e processi (default: no-op)."""
        return None


class NullEngine(Engine):
    """Motore non disponibile: la UI resta usabile e mostra la diagnosi."""

    name = "null"

    def __init__(self, message: str = "", code: str = "engine_unavailable"):
        self._status = EngineStatus(
            available=False,
            code=code,
            message=message
            or "Motore RVC non disponibile: verifica il runtime con la Diagnostica.",
        )

    def status(self) -> EngineStatus:
        return self._status

    def load(self, model_path, index_path="", version="v2", device="auto"):
        raise EngineError(self._status.code, self._status.message)

    def infer(
        self,
        input_path,
        output_path,
        params,
        on_log=None,
        on_stage=None,
        is_cancelled=None,
    ):
        raise EngineError(self._status.code, self._status.message)


class FakeEngine(Engine):
    """Motore deterministico per test: genera un WAV di silenzio."""

    name = "fake"

    def __init__(
        self,
        sample_rate: int = 40000,
        duration_s: float = 0.5,
        delay_s: float = 0.0,
        fail_with: Optional[str] = None,
        available: bool = True,
    ):
        self.sample_rate = sample_rate
        self.duration_s = duration_s
        self.delay_s = delay_s
        self.fail_with = fail_with
        self.available = available
        self._loaded: Optional[Dict[str, str]] = None
        self._cancelled = False
        self._busy = False
        self.logs = []

    def status(self) -> EngineStatus:
        return EngineStatus(
            available=self.available,
            code="" if self.available else "engine_unavailable",
            message="" if self.available else "motore finto non disponibile",
            device="fake",
            requested_device="fake",
            model_path=(self._loaded or {}).get("model", ""),
            index_path=(self._loaded or {}).get("index", ""),
            model_version=(self._loaded or {}).get("version", "v2"),
            loaded=self._loaded is not None,
            warm=self._loaded is not None,
            busy=self._busy,
            extra={"fake": True},
        )

    def load(self, model_path, index_path="", version="v2", device="auto"):
        if not os.path.isfile(model_path):
            raise EngineError("model_invalid", "modello non trovato: %s" % model_path)
        self._loaded = {
            "model": model_path,
            "index": index_path,
            "version": version,
            "device": device,
        }

    def infer(
        self,
        input_path,
        output_path,
        params,
        on_log=None,
        on_stage=None,
        is_cancelled=None,
    ):
        started = time.time()
        self._busy = True
        self._cancelled = False
        try:
            if on_log:
                on_log("fake-engine: avvio inferenza")
            if on_stage:
                on_stage("loading", 0.0)
            if self.delay_s:
                deadline = time.time() + self.delay_s
                while time.time() < deadline:
                    if is_cancelled and is_cancelled():
                        return InferResult(
                            ok=False,
                            error_code="canceled",
                            error_message="Job annullato",
                            elapsed_s=time.time() - started,
                        )
                    time.sleep(0.01)
            if self.fail_with:
                raise EngineError("engine_error", self.fail_with)
            if on_stage:
                on_stage("synthesize", 60.0)
            _write_silence(output_path, self.sample_rate, self.duration_s)
            if on_stage:
                on_stage("write", 100.0)
            return InferResult(
                ok=True,
                output_path=output_path,
                duration_s=self.duration_s,
                sample_rate=self.sample_rate,
                elapsed_s=time.time() - started,
            )
        finally:
            self._busy = False

    def unload(self) -> None:
        self._loaded = None

    def cancel(self) -> None:
        self._cancelled = True


def _write_silence(path: str, sample_rate: int, duration_s: float) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = max(1, int(sample_rate * duration_s))
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        chunk = b"\x00\x00" * min(frames, 4096)
        written = 0
        while written < frames:
            size = min(4096, frames - written)
            handle.writeframes(chunk[: size * 2])
            written += size
    os.replace(tmp, path)


def pcm_peak_amplitude(path: str) -> float:
    """Picco assoluto normalizzato di un WAV PCM (helper per i test)."""
    with wave.open(path, "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        width = handle.getsampwidth()
    if not frames or width != 2:
        return 0.0
    count = len(frames) // 2
    if not count:
        return 0.0
    values = struct.unpack("<%dh" % count, frames[: count * 2])
    return max(abs(value) for value in values) / 32768.0


def rms(path: str) -> float:
    with wave.open(path, "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        width = handle.getsampwidth()
    if not frames or width != 2:
        return 0.0
    count = len(frames) // 2
    if not count:
        return 0.0
    values = struct.unpack("<%dh" % count, frames[: count * 2])
    return math.sqrt(sum(v * v for v in values) / count) / 32768.0
