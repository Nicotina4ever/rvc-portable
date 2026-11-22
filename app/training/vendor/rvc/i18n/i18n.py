"""Traduzioni no-op per il codice di training vendorizzato.

Il training gira in un processo separato e parla solo tramite log e file di
metriche: non serve un catalogo lingue. ``I18nAuto`` restituisce la chiave, cosi'
i messaggi cinesi originali diventano identificatori stabili che il parser dei
log ignora.
"""

from __future__ import annotations


class I18nAuto:
    def __init__(self, language=None):  # noqa: ARG002 - firma compatibile
        self.language = "en_US"

    def __call__(self, key):
        return key

    def __repr__(self) -> str:
        return "I18nAuto(no-op)"
