"""Rotta selezione file: dialog nativo Tk, eseguito fuori dal loop async.

L'import di ``tkinter`` avviene **dentro** la funzione del dialog: la CI e i
server senza display (es. Ubuntu senza ``python3-tk``/DISPLAY) devono poter
importare ``app.api.app_factory`` senza errori. Se Tk non e' disponibile si
risponde ``503 validation_error`` con l'invito a digitare il percorso a mano.

L'endpoint e' una ``def`` sincrona: FastAPI la esegue nel threadpool, quindi il
dialog modale non blocca il loop degli eventi.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request

from ..errors import ApiError

router = APIRouter(tags=["files"])

LOGGER = logging.getLogger("rvc.api")

DIALOG_KINDS = ("directory", "model", "index", "audio", "config")

DEFAULT_TITLES = {
    "directory": "Seleziona cartella",
    "model": "Seleziona modello RVC (.pth)",
    "index": "Seleziona indice RVC (.index)",
    "audio": "Seleziona file audio",
    "config": "Seleziona configurazione (.json)",
}

FILETYPES: Dict[str, List[Tuple[str, str]]] = {
    "model": [
        ("Modelli RVC", "*.pth"),
        ("Tutti i file", "*"),
    ],
    "index": [
        ("Indici RVC", "*.index"),
        ("Tutti i file", "*"),
    ],
    "audio": [
        ("File audio", "*.wav *.mp3 *.ogg *.m4a *.flac"),
        ("Tutti i file", "*"),
    ],
    "config": [
        ("Configurazioni JSON", "*.json"),
        ("Tutti i file", "*"),
    ],
}

UNAVAILABLE_MESSAGE = "selezione file non disponibile: usa il percorso manuale"


class DialogUnavailable(Exception):
    """Tk non disponibile nell'ambiente corrente (display/VNC/server)."""


def _initial_kwargs(initial: str) -> Dict[str, str]:
    """Traduce il percorso iniziale nei kwargs di tkinter.filedialog."""
    kwargs: Dict[str, str] = {}
    if not initial:
        return kwargs
    candidate = os.path.abspath(os.path.expanduser(initial.strip().strip('"')))
    if os.path.isdir(candidate):
        kwargs["initialdir"] = candidate
    elif os.path.isfile(candidate):
        parent = os.path.dirname(candidate)
        if parent and os.path.isdir(parent):
            kwargs["initialdir"] = parent
        kwargs["initialfile"] = os.path.basename(candidate)
    return kwargs


def _open_dialog(kind: str, title: str, initial: str) -> Dict[str, Any]:
    """Apre il dialog nativo (funzione bloccante: eseguita in threadpool)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # ImportError o TclError in ambienti headless
        raise DialogUnavailable("tkinter non disponibile: %s" % exc) from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:  # pragma: no cover - opzione non supportata
            pass
        kwargs: Dict[str, Any] = {"title": title}
        kwargs.update(_initial_kwargs(initial))
        if kind == "directory":
            selected = filedialog.askdirectory(**kwargs)
        else:
            kwargs["filetypes"] = FILETYPES.get(kind) or [("Tutti i file", "*")]
            selected = filedialog.askopenfilename(**kwargs)
        path = str(selected or "").strip()
        return {"path": path or None, "canceled": not bool(path)}
    except Exception as exc:
        raise DialogUnavailable(str(exc)) from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:  # pragma: no cover - distruzione best effort
                pass


@router.post("/api/files/dialog")
def open_dialog(
    request: Request,
    payload: Optional[Dict[str, Any]] = None,
):
    body = payload or {}
    kind = str(body.get("kind") or "directory").strip().lower()
    if kind not in DIALOG_KINDS:
        raise ApiError(
            "validation_error",
            "kind non valido: usa %s" % ", ".join(DIALOG_KINDS),
            422,
            {"field": "kind", "allowed": list(DIALOG_KINDS)},
        )
    title = str(body.get("title") or "").strip() or DEFAULT_TITLES[kind]
    initial = str(body.get("initial") or "").strip()
    try:
        return _open_dialog(kind, title, initial)
    except DialogUnavailable as exc:
        LOGGER.warning("dialog file non disponibile: %s", exc)
        raise ApiError(
            "validation_error",
            UNAVAILABLE_MESSAGE,
            503,
            {},
            str(exc),
        ) from exc
