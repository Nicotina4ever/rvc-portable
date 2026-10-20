"""Test del catalogo traduzioni e della parita' tra lingue."""

from __future__ import annotations

import json
import os

from app.i18n import LocaleCatalog, validate_catalogs


def _write(directory, language, data):
    with open(os.path.join(directory, "%s.json" % language), "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


def test_load_and_fallback(tmp_path):
    _write(str(tmp_path), "it", {"app_title": "Titolo", "greet": "Ciao {name}"})
    catalog = LocaleCatalog(str(tmp_path))
    assert catalog.t("app_title") == "Titolo"
    assert catalog.t("greet", name="Nicola") == "Ciao Nicola"
    assert catalog.t("missing_key") == "missing_key"
    assert catalog.load("de")["app_title"] == "Titolo"  # fallback it
    assert catalog.available() == ["it"]


def test_parity_ok(tmp_path):
    _write(str(tmp_path), "it", {"a": "A", "b": "B"})
    _write(str(tmp_path), "en", {"a": "A", "b": "B"})
    assert validate_catalogs(str(tmp_path)) == []


def test_parity_missing_and_empty(tmp_path):
    _write(str(tmp_path), "it", {"a": "A", "b": "B"})
    _write(str(tmp_path), "en", {"a": "A", "b": " "})
    problems = validate_catalogs(str(tmp_path))
    assert any("chiavi vuote" in problem for problem in problems)

    _write(str(tmp_path), "en", {"a": "A"})
    problems = validate_catalogs(str(tmp_path))
    assert any("chiavi mancanti" in problem for problem in problems)


def test_repo_catalogs_are_consistent():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    locales = os.path.join(root, "locales")
    if not os.path.isdir(locales) or not os.listdir(locales):
        return  # il frontend non ha ancora creato i cataloghi
    assert validate_catalogs(locales) == []
