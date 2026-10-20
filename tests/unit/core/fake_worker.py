"""Worker RVC finto per i test del motore, senza torch.

Implementa lo stesso protocollo JSONL di ``app.core.worker`` (vedi il suo
docstring) ma produce un WAV sinusoidale e simula latenza/crash. Viene avviato
da ``RvcEngine`` nei test al posto del worker reale tramite ``worker_command``.

Uso:  python -B tests/unit/core/fake_worker.py --device cpu
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import wave

STAGE_DELAY_S = 0.02
INFER_DELAY_S = 0.25
SAMPLE_RATE = 16000


def _write_tone(path: str, seconds: float = 0.3, sample_rate: int = SAMPLE_RATE) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = int(seconds * sample_rate)
    payload = bytearray()
    for index in range(frames):
        value = int(12000 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
        payload += int(value).to_bytes(2, "little", signed=True)
    tmp = path + ".fake-tmp"
    with wave.open(tmp, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    os.replace(tmp, path)


class FakeWorker:
    def __init__(self, device: str):
        self.device = device
        self.model = ""
        self.index = ""
        self.version = "v2"
        self.loaded = False
        self.cancel = threading.Event()
        self.busy = False
        self._lock = threading.Lock()

    def send(self, payload) -> None:
        with self._lock:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def stage(self, name: str, pct: float) -> None:
        self.send({"ev": "stage", "name": name, "pct": pct})

    def infer(self, request) -> None:
        request_id = request.get("id")
        params = request.get("params") or {}
        output = str(request.get("output") or "")
        self.cancel.clear()
        self.busy = True
        started = time.time()
        try:
            for name, pct in (
                ("extract", 10.0),
                ("f0", 30.0),
                ("features", 55.0),
                ("synthesize", 75.0),
                ("write", 90.0),
            ):
                if self.cancel.is_set():
                    raise _Canceled()
                self.stage(name, pct)
                time.sleep(STAGE_DELAY_S)
            audio_seconds = float(params.get("fake_seconds") or 0.0) or 0.3
            remaining = INFER_DELAY_S
            while remaining > 0:
                if self.cancel.is_set():
                    raise _Canceled()
                time.sleep(min(0.02, remaining))
                remaining -= 0.02
            self.send({"ev": "log", "message": "fake: scrittura output"})
            _write_tone(output, seconds=audio_seconds)
            if self.cancel.is_set():
                raise _Canceled()
            self.stage("done", 100.0)
            self.send(
                {
                    "ev": "done",
                    "id": request_id,
                    "ok": True,
                    "output": os.path.abspath(output),
                    "duration_s": audio_seconds,
                    "sample_rate": SAMPLE_RATE,
                    "elapsed_s": round(time.time() - started, 3),
                    "frames": int(audio_seconds * SAMPLE_RATE),
                }
            )
        except _Canceled:
            self.send(
                {
                    "ev": "error",
                    "id": request_id,
                    "ok": False,
                    "code": "canceled",
                    "message": "Job annullato",
                    "detail": "",
                }
            )
        finally:
            self.busy = False

    def handle(self, request) -> bool:
        op = str(request.get("op") or "")
        request_id = request.get("id")
        if op == "ping":
            self.send(
                {
                    "ev": "result",
                    "id": request_id,
                    "ok": True,
                    "data": {"pong": True, "pid": os.getpid(), "device": self.device},
                }
            )
        elif op == "status":
            self.send(
                {
                    "ev": "result",
                    "id": request_id,
                    "ok": True,
                    "data": {
                        "device": self.device,
                        "loaded": self.loaded,
                        "model": self.model,
                        "index": self.index,
                        "version": self.version,
                        "busy": self.busy,
                        "torch": "fake",
                        "tgt_sr": SAMPLE_RATE,
                    },
                }
            )
        elif op == "load":
            model = str(request.get("model") or "")
            index = str(request.get("index") or "")
            if not os.path.isfile(model):
                self.send(
                    {
                        "ev": "error",
                        "id": request_id,
                        "ok": False,
                        "code": "model_invalid",
                        "message": "modello non trovato: %s" % model,
                        "detail": "",
                    }
                )
                return True
            self.model = model
            self.index = index
            self.version = str(request.get("version") or "v2")
            self.loaded = True
            self.send(
                {
                    "ev": "result",
                    "id": request_id,
                    "ok": True,
                    "data": {
                        "device": self.device,
                        "loaded": True,
                        "model": self.model,
                        "index": self.index,
                        "version": self.version,
                        "tgt_sr": SAMPLE_RATE,
                    },
                }
            )
        elif op == "infer":
            if not self.loaded:
                self.send(
                    {
                        "ev": "error",
                        "id": request_id,
                        "ok": False,
                        "code": "engine_unavailable",
                        "message": "nessun modello caricato",
                        "detail": "",
                    }
                )
            else:
                self.infer(request)
        elif op == "cancel":
            self.cancel.set()
            self.send(
                {"ev": "result", "id": request_id, "ok": True, "data": {"canceled": True}}
            )
        elif op == "unload":
            self.loaded = False
            self.send(
                {
                    "ev": "result",
                    "id": request_id,
                    "ok": True,
                    "data": {"unloaded": True, "device": self.device, "loaded": False},
                }
            )
        elif op == "crash":
            os._exit(7)
        elif op == "shutdown":
            self.send(
                {"ev": "result", "id": request_id, "ok": True, "data": {"shutdown": True}}
            )
            return False
        else:
            self.send(
                {
                    "ev": "error",
                    "id": request_id,
                    "ok": False,
                    "code": "protocol_error",
                    "message": "operazione sconosciuta: %r" % op,
                    "detail": "",
                }
            )
        return True


class _Canceled(Exception):
    pass


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    device = "cpu"
    for index, value in enumerate(args):
        if value == "--device" and index + 1 < len(args):
            device = args[index + 1]
    worker = FakeWorker(device)
    requests = []
    lock = threading.Lock()
    done = threading.Event()

    def reader() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                continue
            if str(request.get("op")) == "cancel":
                worker.cancel.set()
                worker.send(
                    {
                        "ev": "result",
                        "id": request.get("id"),
                        "ok": True,
                        "data": {"canceled": True},
                    }
                )
                continue
            with lock:
                requests.append(request)
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    worker.send({"ev": "log", "message": "fake worker pronto"})
    while not done.is_set() or requests:
        with lock:
            try:
                request = requests.pop(0)
            except IndexError:
                request = None
        if request is None:
            time.sleep(0.01)
            continue
        if not worker.handle(request):
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
