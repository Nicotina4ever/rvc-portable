"""Selezione device/precisione per il training (estratto da RVC1006Nvidia).

Regole: GPU sotto 4 GiB o SM < 5.3 non sono ammesse; Pascal SM 6.1 e GTX 16
usano fp32; le GPU piu' recenti possono usare fp16. Su CPU il training resta
possibile ma lento: il backend lo sconsiglia esplicitamente.
"""

from __future__ import annotations

import logging
import re

import torch

logger = logging.getLogger(__name__)


def get_device_dtype_sm(idx):
    cpu = torch.device("cpu")
    if not torch.cuda.is_available() or idx < 0 or idx >= torch.cuda.device_count():
        return cpu, torch.float32, 0.0, 0.0

    try:
        cuda = torch.device("cuda:%d" % idx)
        major, minor = torch.cuda.get_device_capability(idx)
        gpu_name = torch.cuda.get_device_name(idx)
        mem_bytes = torch.cuda.get_device_properties(idx).total_memory
    except Exception:
        logger.exception("Unable to inspect CUDA device %s", idx)
        return cpu, torch.float32, 0.0, 0.0

    mem_gb = mem_bytes / (1024**3) + 0.4
    sm_version = major + minor / 10.0
    is_16_series = bool(re.search(r"16\d{2}", gpu_name)) and sm_version == 7.5
    if mem_gb < 4 or sm_version < 5.3:
        return cpu, torch.float32, 0.0, 0.0
    if sm_version == 6.1 or is_16_series:
        return cuda, torch.float32, sm_version, mem_gb
    if sm_version > 6.1:
        return cuda, torch.float16, sm_version, mem_gb
    return cpu, torch.float32, 0.0, 0.0


def get_training_dtype():
    """Precisione condivisa; con una sola GPU usa il suo profilo."""
    if not torch.cuda.is_available():
        return torch.float32

    profiles = [get_device_dtype_sm(i) for i in range(torch.cuda.device_count())]
    unsupported = [i for i, profile in enumerate(profiles) if profile[0].type != "cuda"]
    if unsupported:
        raise RuntimeError(
            "GPU non idonee al training (servono >= 4 GiB e SM 5.3): %s" % unsupported
        )
    if profiles and all(profile[1] == torch.float16 for profile in profiles):
        return torch.float16
    return torch.float32
