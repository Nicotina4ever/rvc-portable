"""Stub di CUDA graph.

Il codice upstream usa i CUDA graph per accelerare l'inferenza di HuBERT e
RMVPE. Su torch 2.0 e su GPU con poca VRAM i graph non sono affidabili e non
servono al training: qui tutto passa dal percorso normale.
"""

from __future__ import annotations


def run_cuda_graph(model, key, fn, *args, **kwargs):
    return fn(*args, **kwargs)


def configure_cuda_graph(*args, **kwargs):  # noqa: ARG001 - firma compatibile
    return False
