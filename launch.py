"""Launcher radice: funziona anche con pythonw (nessuna console).

``run.bat``/``run.sh``/``run.command`` puntano qui. Inseriamo la radice del
progetto in ``sys.path`` prima di importare ``app``: necessario perche' il
runtime embeddable usa ``python39._pth`` e non aggiunge la cartella dello
script al path.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.cli import main  # noqa: E402


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        # Ultima rete di sicurezza sotto pythonw: scrivi il traceback nel log.
        import traceback

        try:
            error_log = os.path.join(ROOT, "data", "logs", "fatal.log")
            os.makedirs(os.path.dirname(error_log), exist_ok=True)
            with open(error_log, "a", encoding="utf-8") as handle:
                handle.write(traceback.format_exc() + "\n")
        except OSError:
            pass
        raise
