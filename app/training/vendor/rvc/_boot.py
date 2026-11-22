"""Bootstrap per eseguire i moduli vendorizzati quando il runtime usa ``._pth``.

Il Python portatile di RVC Portable ha ``python39._pth``: in modalita' isolata
``PYTHONPATH`` viene ignorato. Questo script aggiunge la cartella vendor a
``sys.path`` e delega a ``runpy``, mantenendo ``sys.argv`` corretto e
compatibile con ``multiprocessing`` (che eredita ``sys.path``).
"""

from __future__ import annotations

import os
import runpy
import sys


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: _boot.py <module> [args...]\n")
        return 2
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    vendor_root = os.path.dirname(os.path.abspath(__file__))
    if vendor_root not in sys.path:
        sys.path.insert(0, vendor_root)
    module = sys.argv[1]
    sys.argv = [module] + sys.argv[2:]
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
