"""HuBERT/ContentVec per il training, via fairseq.

Il codice upstream (RVC1006Nvidia) usa un modello Transformers, che non fa parte
del runtime di RVC Portable. Qui si usa lo stesso ``hubert_base.pt`` che serve
all'inferenza (fairseq), gia' presente in ``rvc_python/base_model``: le feature
sono equivalenti a quelle usate da RVC per il training v1/v2.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)


def resolve_hubert_path() -> str:
    explicit = os.environ.get("RVC_HUBERT_PATH", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    try:
        import rvc_python

        candidate = os.path.join(
            os.path.dirname(os.path.abspath(rvc_python.__file__)),
            "base_model",
            "hubert_base.pt",
        )
        if os.path.isfile(candidate):
            return candidate
    except Exception:
        pass
    raise FileNotFoundError(
        "hubert_base.pt non trovato: imposta RVC_HUBERT_PATH o installa rvc_python"
    )


HUBERT_MODEL_PATH = os.environ.get("RVC_HUBERT_PATH", "")


@lru_cache(maxsize=1)
def hubert_audio_requires_normalization() -> bool:
    """Il checkpoint fairseq di RVC non applica la normalizzazione Transformers."""
    return False


def load_hubert_model(device, is_half: bool = False):
    """Carica HuBERT e lo porta su ``device`` (fp16 opzionale)."""
    from fairseq import checkpoint_utils

    path = resolve_hubert_path()
    logger.info("Loading HuBERT (fairseq) from %s on %s", path, device)
    models, _saved, _task = checkpoint_utils.load_model_ensemble_and_task([path])
    model = models[0]
    model = model.to(device)
    if is_half:
        model = model.half()
    model.eval()
    return model


def extract_hubert_features(
    model,
    source: np.ndarray,
    version: str = "v2",
    padding_mask: Optional["torch.Tensor"] = None,
    device=None,
    is_half: bool = False,
) -> np.ndarray:
    """Estrae feature 256-D (v1) o 768-D (v2) da audio 16 kHz.

    ``source`` puo' essere 1-D o con forma ``(1, N)``. Restituisce un array
    ``(T, dim)`` pronto per ``np.save``.
    """
    if version not in ("v1", "v2"):
        raise ValueError("versione feature non supportata: %r" % (version,))

    tensor = torch.from_numpy(np.asarray(source, dtype=np.float32)).float()
    tensor = tensor.view(1, -1)
    if device is None:
        device = next(model.parameters()).device
    tensor = tensor.to(device)
    if is_half:
        tensor = tensor.half()
    if padding_mask is None:
        padding_mask = torch.BoolTensor(tensor.shape).fill_(False).to(device)

    inputs = {
        "source": tensor,
        "padding_mask": padding_mask,
        "output_layer": 9 if version == "v1" else 12,
    }
    with torch.no_grad():
        output = model.extract_features(**inputs)
        hidden = output[0] if isinstance(output, (tuple, list)) else output
        if version == "v1":
            feats = model.final_proj(hidden)
        else:
            feats = hidden
    if feats.dim() == 3:
        if feats.shape[0] == 1:
            feats = feats.squeeze(0)
        elif feats.shape[1] == 1:
            feats = feats.squeeze(1)
    return feats.detach().float().cpu().numpy()
