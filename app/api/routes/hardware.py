"""Rotta hardware: probe del runtime motore e device disponibili.

Il backend non importa torch: ``app.core.devices.probe_engine`` esegue il probe
in un sottoprocesso del runtime del motore (con cache TTL) e restituisce un
oggetto serializzabile.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Request

from ...core import devices
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["hardware"])

LOGGER = logging.getLogger("rvc.api")

DIRECTML_NOTE = (
    "DirectML non e' supportato dal motore rvc-python: usa auto, cpu, cuda "
    "oppure mps (solo macOS)."
)


def _probe(request: Request) -> devices.RuntimeProbe:
    paths = deps.paths(request)
    try:
        return devices.probe_engine(paths)
    except NotImplementedError:
        raise ApiError(
            "engine_unavailable",
            "Probe hardware non ancora disponibile: riprova dopo l'aggiornamento",
            503,
        ) from None
    except (OSError, ValueError) as exc:
        LOGGER.warning("probe hardware fallito: %s", exc)
        raise ApiError(
            "engine_unavailable",
            "Probe hardware fallito: %s" % exc,
            503,
            {},
            repr(exc),
        ) from exc


def _device_options(
    probe: devices.RuntimeProbe, effective: str
) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = [
        {
            "id": "auto",
            "label": "Automatico",
            "available": True,
            "reason": "seleziona il device migliore (%s)" % effective,
        },
        {
            "id": "cpu",
            "label": "CPU",
            "available": True,
            "reason": "sempre disponibile, piu' lento della GPU",
        },
    ]
    if probe.cuda:
        label = "GPU CUDA 0"
        if probe.gpu_name:
            label = "GPU CUDA 0 - %s" % probe.gpu_name
        reason = "CUDA disponibile"
        if probe.vram_gb:
            reason += " (%.1f GB VRAM)" % probe.vram_gb
        options.append(
            {"id": "cuda:0", "label": label, "available": True, "reason": reason}
        )
    if probe.mps:
        options.append(
            {
                "id": "mps",
                "label": "Apple Silicon (MPS)",
                "available": True,
                "reason": "MPS disponibile (sperimentale per RVC)",
            }
        )
    return options


@router.get("/api/hardware")
def get_hardware(request: Request):
    probe = _probe(request)
    settings = deps.settings_manager(request).settings
    requested = str(settings.engine.device or "auto")
    effective, warnings = devices.effective_device(requested, probe)
    try:
        system = devices.system_info()
    except Exception as exc:  # pragma: no cover - informazioni opzionali
        LOGGER.warning("system_info non disponibile: %s", exc)
        system = {}
    return {
        "probe": probe.to_dict(),
        "system": system,
        "devices": _device_options(probe, effective),
        "requested_device": requested,
        "effective_device": effective,
        "warnings": list(warnings),
        "notes": [DIRECTML_NOTE],
        "directml_supported": False,
    }
