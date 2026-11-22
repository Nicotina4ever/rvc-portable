"""Preset di addestramento: rendono la scelta semplice senza nascondere i parametri."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class TrainingPreset:
    id: str
    label: str
    description: str
    epochs: int
    batch_size: int
    save_every: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


PRESETS: Dict[str, TrainingPreset] = {
    "veloce": TrainingPreset(
        id="veloce",
        label="Veloce",
        description="Test rapidi: meno epoche, batch grande. Utile per provare un dataset.",
        epochs=120,
        batch_size=8,
        save_every=20,
    ),
    "bilanciato": TrainingPreset(
        id="bilanciato",
        label="Bilanciato",
        description="Compromesso consigliato per la maggior parte dei dataset (15-30 minuti).",
        epochs=250,
        batch_size=6,
        save_every=20,
    ),
    "qualita": TrainingPreset(
        id="qualita",
        label="Qualita'",
        description="Piu' epoche e batch piccolo: dataset lunghi e puliti, tempi piu' alti.",
        epochs=400,
        batch_size=4,
        save_every=25,
    ),
}

DEFAULT_PRESET = "bilanciato"


def preset_list() -> List[Dict[str, Any]]:
    return [preset.to_dict() for preset in PRESETS.values()]


def get_preset(preset_id: str) -> TrainingPreset:
    key = str(preset_id or "").strip().lower()
    return PRESETS.get(key) or PRESETS[DEFAULT_PRESET]
