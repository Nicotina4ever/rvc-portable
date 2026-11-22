"""``SummaryWriter`` leggero: niente TensorBoard, metriche in JSON Lines.

Il training upstream scrive curve su TensorBoard. RVC Portable non installa
TensorBoard: questo shim registra ``{"tag", "value", "step"}`` in
``RVC_TRAIN_METRICS`` (o ``<log_dir>/metrics.jsonl``), cosi' la UI puo'
disegnare la loss senza dipendenze extra.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional


class SummaryWriter:  # noqa: N801 - nome compatibile con torch.utils.tensorboard
    def __init__(self, log_dir: Optional[str] = None, **_kwargs):
        self.log_dir = log_dir or ""
        explicit = os.environ.get("RVC_TRAIN_METRICS", "").strip()
        if explicit:
            self.path = explicit
        elif self.log_dir:
            os.makedirs(self.log_dir, exist_ok=True)
            self.path = os.path.join(self.log_dir, "metrics.jsonl")
        else:
            self.path = ""
        self._lock = threading.Lock()
        self._closed = False

    def add_scalar(self, tag: str, scalar_value: Any, global_step: Optional[int] = None, **_kwargs) -> None:
        if self._closed or not self.path:
            return
        try:
            value = float(scalar_value)
        except (TypeError, ValueError):
            return
        if value != value or value in (float("inf"), float("-inf")):
            return
        record: Dict[str, Any] = {"tag": str(tag), "value": value}
        if global_step is not None:
            try:
                record["step"] = int(global_step)
            except (TypeError, ValueError):
                pass
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                self._closed = True

    def add_histogram(self, *_args, **_kwargs) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self._closed = True
