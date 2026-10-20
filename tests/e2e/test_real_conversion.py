"""E2E reale del motore RVC (pytest): esegue lo script ``run_real_conversion.py``.

Questo test e' **opt-in**: richiede runtime con torch/CUDA, i pesi base e i
modelli in ``Modelli/``, e scalda la GPU. Si abilita con::

    $env:RVC_E2E = "1"
    runtime\\python.exe -B -m pytest tests\\e2e -q -m e2e

Senza la variabile d'ambiente viene saltato (la suite normale resta veloce e
deterministica).
"""

from __future__ import annotations

import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "tests", "e2e", "run_real_conversion.py")
RUNTIME_PYTHON = os.path.join(ROOT, "runtime", "python.exe")
MODEL = os.path.join(ROOT, "Modelli", "Nicola-Spot2.pth")
INDEX = os.path.join(
    ROOT, "Modelli", "added_IVF1456_Flat_nprobe_1_Nicola-Spot2_v2.index"
)

pytestmark = pytest.mark.e2e


def _ready() -> bool:
    if os.environ.get("RVC_E2E") != "1":
        return False
    if not os.path.isfile(RUNTIME_PYTHON):
        return False
    return os.path.isfile(MODEL) and os.path.isfile(INDEX)


@pytest.mark.skipif(not _ready(), reason="E2E reale disabilitato (imposta RVC_E2E=1)")
def test_real_conversion_end_to_end():
    command = [
        RUNTIME_PYTHON,
        "-B",
        SCRIPT,
        "--seconds",
        "4",
        "--device",
        os.environ.get("RVC_E2E_DEVICE", "cuda:0"),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0, output[-4000:]
    assert "E2E OK" in output, output[-2000:]
    assert "Modelli/ invariata" in output
