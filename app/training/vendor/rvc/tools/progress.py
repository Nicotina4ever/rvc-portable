"""Helper di avanzamento per la pipeline vendorizzata.

Il formato e' volutamente semplice e stabile, cosi' il parser Python del
backend (``app/training/pipeline.py``) puo' leggere ``PROGRESS <done> <total>``
senza dipendere dalla lingua o dalla versione del codice upstream.
"""

from __future__ import annotations

import math


def should_report(index, total, max_updates=12):
    if total <= 0:
        return False
    if total <= max_updates:
        return True
    interval = max(1, math.ceil(total / max_updates))
    return index == 0 or index + 1 == total or (index + 1) % interval == 0


def batch_status(title, current, total, success, failed, latest="", failures=None):
    if total <= 0:
        state = "waiting"
    elif current >= total:
        state = "done"
    else:
        state = "running"
    lines = [
        "[%s]" % title,
        "state: %s" % state,
        "progress: %s/%s | ok: %s | failed: %s" % (current, total, success, failed),
    ]
    if latest:
        lines.append("current: %s" % latest)
    if failures:
        lines.append("failures:")
        lines.extend(failures[-10:])
    return "\n".join(lines)
