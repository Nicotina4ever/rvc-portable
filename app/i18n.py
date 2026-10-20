"""Catalogo traduzioni condiviso tra backend e frontend (IT/EN)."""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

DEFAULT_LANGUAGE = "it"
FALLBACK_LANGUAGE = "it"


class LocaleError(Exception):
    pass


class LocaleCatalog:
    """Carica ``locales/{lang}.json`` con fallback e cache in memoria."""

    def __init__(self, locales_dir: str):
        self.locales_dir = locales_dir
        self._cache: Dict[str, Dict[str, str]] = {}
        self.language = DEFAULT_LANGUAGE
        self.strings: Dict[str, str] = {}
        self.load(DEFAULT_LANGUAGE)

    def available(self) -> List[str]:
        try:
            names = [
                name[:-5]
                for name in os.listdir(self.locales_dir)
                if name.endswith(".json")
            ]
        except OSError:
            return [FALLBACK_LANGUAGE]
        return sorted(names) or [FALLBACK_LANGUAGE]

    def load(self, language: str) -> Dict[str, str]:
        language = (language or DEFAULT_LANGUAGE).strip().lower()
        if language in self._cache:
            self.language, self.strings = language, self._cache[language]
            return self.strings
        data = self._read(language)
        if data is None and language != FALLBACK_LANGUAGE:
            data = self._read(FALLBACK_LANGUAGE)
            language = FALLBACK_LANGUAGE
        if data is None:
            data = {}
        self._cache[language] = data
        self.language, self.strings = language, data
        return data

    def _read(self, language: str) -> Optional[Dict[str, str]]:
        path = os.path.join(self.locales_dir, "%s.json" % language)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return {str(k): str(v) for k, v in data.items()}

    def catalog(self, language: Optional[str] = None) -> Dict[str, str]:
        return self.load(language) if language else self.strings

    def t(self, key: str, **params) -> str:
        text = self.strings.get(key, key)
        if params:
            try:
                return text.format(**params)
            except (KeyError, IndexError, ValueError):
                return text
        return text


def validate_catalogs(locales_dir: str) -> List[str]:
    """Ritorna i problemi di parita' tra i cataloghi (usato dai test)."""
    problems: List[str] = []
    available = LocaleCatalog(locales_dir).available()
    if FALLBACK_LANGUAGE not in available:
        problems.append("catalogo di fallback '%s' mancante" % FALLBACK_LANGUAGE)
    base: Optional[Dict[str, str]] = None
    for language in available:
        catalog = LocaleCatalog(locales_dir)
        strings = catalog.load(language)
        if base is None and language == FALLBACK_LANGUAGE:
            base = strings
        empty = [key for key, value in strings.items() if not str(value).strip()]
        if empty:
            problems.append("%s: chiavi vuote: %s" % (language, ", ".join(sorted(empty))))
    if base is not None:
        for language in available:
            if language == FALLBACK_LANGUAGE:
                continue
            catalog = LocaleCatalog(locales_dir)
            strings = catalog.load(language)
            missing = sorted(set(base) - set(strings))
            extra = sorted(set(strings) - set(base))
            if missing:
                problems.append("%s: chiavi mancanti: %s" % (language, ", ".join(missing)))
            if extra:
                problems.append("%s: chiavi extra: %s" % (language, ", ".join(extra)))
    return problems
