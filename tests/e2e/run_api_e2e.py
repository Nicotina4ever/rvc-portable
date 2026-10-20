"""E2E reale via API: avvia il backend, converte un file con il motore RVC e verifica
audio, Range, waveform e shutdown.

Prerequisiti: runtime del motore con CUDA (o CPU), modelli in Modelli/.
Esecuzione:  runtime\\python.exe -B tests\\e2e\\run_api_e2e.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import wave

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

PORT = 8770
BASE = "http://127.0.0.1:%d" % PORT
MODEL = os.path.join("Modelli", "Nicola-Spot2.pth")
INDEX = os.path.join("Modelli", "added_IVF1456_Flat_nprobe_1_Nicola-Spot2_v2.index")
SAMPLE = os.path.join("data", "cache", "gate0-sample.wav")
LOG = os.path.join("data", "logs", "e2e-api.log")


def make_sample(path: str, seconds: float = 4.0, rate: int = 16000) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frames = int(seconds * rate)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        payload = bytearray()
        for index in range(frames):
            value = 0.4 * ((index * 37) % 200 - 100) / 100.0
            value += 0.3 * ((index * 11) % 100) / 100.0 - 0.15
            payload += int(max(-1.0, min(1.0, value)) * 16000).to_bytes(2, "little", signed=True)
        handle.writeframes(bytes(payload))


def main() -> int:
    if os.path.exists(os.path.join("data", "state", "instance.json")):
        try:
            with open(os.path.join("data", "state", "instance.json"), "r", encoding="utf-8") as fh:
                info = json.load(fh)
            if info.get("pid"):
                print("[e2e] esiste gia' un'istanza (pid %s): la ignoro" % info["pid"])
        except (OSError, ValueError):
            pass
    for path in (MODEL, INDEX):
        if not os.path.isfile(path):
            print("[e2e] manca %s" % path)
            return 2
    if not os.path.isfile(SAMPLE):
        make_sample(SAMPLE)
        print("[e2e] creato campione sintetico %s" % SAMPLE)

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log_handle = open(LOG, "a", encoding="utf-8")
    command = [
        sys.executable,
        "-B",
        "-m",
        "app",
        "--headless",
        "--port",
        str(PORT),
        "--console",
        "--idle-exit-minutes",
        "0",
    ]
    print("[e2e] avvio backend: %s" % " ".join(command))
    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    token = ""
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                response = requests.get(BASE + "/api/health", timeout=1)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.2)
        else:
            print("[e2e] backend non avviato")
            return 1
        with open(os.path.join("data", "state", "session.json"), "r", encoding="utf-8") as fh:
            token = json.load(fh)["token"]
        auth = {"Authorization": "Bearer %s" % token}
        meta = requests.get(BASE + "/api/meta", headers=auth, timeout=30).json()
        engine = meta.get("engine") or {}
        print("[e2e] engine: available=%s device=%s" % (engine.get("available"), engine.get("device")))
        if not engine.get("available"):
            print("[e2e] motore non disponibile: %s" % engine.get("message"))
            return 1

        payload = {
            "input": os.path.abspath(SAMPLE),
            "model": os.path.abspath(MODEL),
            "index": os.path.abspath(INDEX),
            "params": {
                "pitch": 0,
                "method": "rmvpe",
                "protect": 0.33,
                "index_rate": 0.3,
                "filter_radius": 3,
                "rms_mix_rate": 0.25,
                "resample_sr": 0,
                "model_version": "v2",
                "output_format": "wav",
            },
        }
        response = requests.post(BASE + "/api/jobs", json=payload, headers=auth, timeout=30)
        if response.status_code != 200:
            print("[e2e] enqueue fallita: %s %s" % (response.status_code, response.text[:400]))
            return 1
        job = response.json()
        job_id = job["id"]
        print("[e2e] job %s accodato" % job_id)
        started = time.time()
        last_stage = None
        current = {}
        while time.time() - started < 240:
            current = requests.get(
                BASE + "/api/jobs/%s" % job_id, headers=auth, timeout=30
            ).json()
            if current.get("stage") != last_stage:
                last_stage = current.get("stage")
                print(
                    "[e2e] stato=%s stage=%s progress=%s"
                    % (current.get("state"), last_stage, current.get("progress"))
                )
            if current.get("state") in ("done", "failed", "canceled"):
                break
            time.sleep(0.4)
        job = current
        if job.get("id") != job_id:
            print("[e2e] risposta job inattesa: %s" % json.dumps(current, indent=2)[:800])
            return 1
        if job.get("state") != "done":
            print("[e2e] job non completato: %s" % json.dumps(job, indent=2)[:1200])
            return 1
        output_path = job["output_path"]
        info = requests.get(
            BASE + "/api/jobs/%s/audio/output" % job["id"], headers=auth, timeout=30
        )
        ranged = requests.get(
            BASE + "/api/jobs/%s/audio/output" % job["id"],
            headers=dict(auth, Range="bytes=0-63"),
            timeout=30,
        )
        waveform = requests.get(
            BASE + "/api/jobs/%s/waveform?side=output&buckets=64" % job["id"],
            headers=auth,
            timeout=60,
        ).json()
        print("[e2e] output: %s | %.2f s @ %d Hz | elapsed %.2f s | RTF %.2f"
              % (os.path.basename(output_path), job.get("duration_s", 0), job.get("sample_rate", 0),
                 job.get("elapsed_s", 0), (job.get("elapsed_s", 0) or 0) / max(job.get("duration_s", 0) or 1, 0.01)))
        print("[e2e] audio: %s (Range: %s, %d byte) | waveform: %d picchi (%.2f s)"
              % (info.status_code, ranged.status_code, len(ranged.content),
                 len(waveform.get("peaks") or []), waveform.get("duration_s", 0)))
        checks = {
            "output_exists": os.path.isfile(output_path),
            "audio_200": info.status_code == 200,
            "range_206": ranged.status_code == 206 and len(ranged.content) == 64,
            "waveform_64": len(waveform.get("peaks") or []) == 64,
            "not_silent": max(waveform.get("peaks") or [0]) > 0.001,
        }
        print("[e2e] checks: %s" % checks)
        if not all(checks.values()):
            return 1
        shutdown = requests.post(BASE + "/api/system/shutdown", headers=auth, timeout=10)
        print("[e2e] shutdown: %s" % shutdown.status_code)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            print("[e2e] ATTENZIONE: il backend non si e' spento entro 20s")
            proc.kill()
            return 1
        print("[e2e] OK — conversione reale via API, audio Range, waveform e shutdown verificati")
        return 0
    finally:
        log_handle.close()
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
