"""Entry point del package: ``python -m app``."""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
