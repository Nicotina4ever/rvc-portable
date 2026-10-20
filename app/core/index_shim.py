"""Compatibilita' indici RVC ``trained_*`` -> ``added_*``.

``rvc_python`` (``modules/vc/modules.py::vc_single``) riscrive il percorso
dell'indice sostituendo ``trained`` con ``added``: se il file "added" non
esiste l'indice viene ignorato in silenzio: niente errore, qualita' peggiore e
nessun indizio per l'utente.

Questo modulo risolve il problema **senza mai toccare i file dell'utente**
(la cartella ``Modelli/`` e' in sola lettura per l'applicazione):
- se esiste gia' il gemello ``added_*`` accanto al ``trained_*`` lo usa;
- altrimenti crea un alias nella cache dell'applicazione (hardlink quando
  possibile, copia atomica come fallback) e restituisce quel percorso.

L'alias viene invalidato/ricreato se il file originale cambia (dimensione o
mtime), cosi' un indice aggiornato dall'utente non resta "congelato".
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil

LOGGER = logging.getLogger("rvc.index_shim")

ALIAS_SUBDIR = "indices"
TRAINED = "trained"
ADDED = "added"


def resolved_index_path(index_path: str, cache_dir: str) -> str:
    """Percorso dell'indice utilizzabile da ``rvc_python``.

    - stringa vuota -> stringa vuota;
    - percorso senza ``trained`` nel nome -> invariato;
    - gemello ``added_*`` esistente -> percorso del gemello;
    - altrimenti -> alias stabile dentro ``<cache_dir>/indices``.
    """
    if not index_path:
        return ""
    path = os.path.abspath(os.path.expanduser(str(index_path).strip().strip('"')))
    directory, basename = os.path.split(path)
    if TRAINED not in basename:
        return path
    if not os.path.isfile(path):
        # File assente: lasciamo decidere al chiamante (warning/errore).
        return path

    sibling = os.path.join(directory, basename.replace(TRAINED, ADDED))
    if os.path.isfile(sibling):
        return sibling

    if not cache_dir:
        return path
    try:
        return _make_alias(path, cache_dir)
    except OSError as exc:  # pragma: no cover - dipende dal filesystem
        LOGGER.warning("alias indice non creato per %s: %s", path, exc)
        return path


def _make_alias(source: str, cache_dir: str) -> str:
    directory = os.path.join(os.path.abspath(cache_dir), ALIAS_SUBDIR)
    os.makedirs(directory, exist_ok=True)
    basename = os.path.basename(source).replace(TRAINED, ADDED)
    digest = hashlib.sha1(os.path.normcase(source).encode("utf-8")).hexdigest()[:16]
    target = os.path.join(directory, "%s-%s" % (digest, basename))

    if _alias_is_current(source, target):
        return target

    tmp = target + ".tmp-%d" % os.getpid()
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        try:
            os.link(source, tmp)
        except OSError:
            shutil.copy2(source, tmp)
        os.replace(tmp, target)
        _write_stamp(source, target)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    LOGGER.info("alias indice creato: %s -> %s", source, target)
    return target


def _alias_is_current(source: str, target: str) -> bool:
    try:
        source_stat = os.stat(source)
        target_stat = os.stat(target)
    except OSError:
        return False
    if source_stat.st_size != target_stat.st_size:
        return False
    # Hardlink: stesso inode, niente da confrontare oltre.
    try:
        if os.path.samefile(source, target):
            return True
    except OSError:
        pass
    return _read_stamp(target) == _fingerprint(source)


def _fingerprint(path: str) -> str:
    stat = os.stat(path)
    return "%d:%d" % (int(stat.st_size), int(getattr(stat, "st_mtime_ns", stat.st_mtime * 1e9)))


def _stamp_path(target: str) -> str:
    return target + ".stamp"


def _write_stamp(source: str, target: str) -> None:
    try:
        with open(_stamp_path(target), "w", encoding="utf-8") as handle:
            handle.write(_fingerprint(source))
    except OSError:  # pragma: no cover
        pass


def _read_stamp(target: str) -> str:
    try:
        with open(_stamp_path(target), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""
