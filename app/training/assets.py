"""Ricerca (e download) dei pesi necessari al training.

- HuBERT e RMVPE arrivano dal runtime ``rvc_python`` gia' installato.
- I generatori/discriminatori pre-addestrati (``f0G48k.pth``, ``f0D48k.pth``,
  ...) vengono cercati in ordine: cartella configurata, cartella dell'app,
  installazioni RVC locali note; se mancano e il download e' abilitato si
  scaricano da HuggingFace (repo ufficiale VoiceConversionWebUI).
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from importlib import util as importlib_util
from typing import Any, Callable, Dict, List, Optional

HF_BASE = "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main"
USER_AGENT = "RVC-Portable/training"
KNOWN_LOCAL_DIRS = (
    r"D:\AI\RVC1006Nvidia\assets",
    r"K:\AI\ultimate-rvc\models\rvc\pretraineds\hifi-gan",
)

Progress = Callable[[str], None]


def runtime_base_model_dir(paths=None) -> Optional[str]:
    """Cartella ``base_model`` di rvc_python, senza importare torch."""
    if paths is not None:
        runtime = getattr(paths, "runtime_dir", "")
        if runtime:
            candidate = os.path.join(
                runtime, "Lib", "site-packages", "rvc_python", "base_model"
            )
            if os.path.isdir(candidate):
                return candidate
            candidate = os.path.join(
                runtime, "lib", "python3.9", "site-packages", "rvc_python", "base_model"
            )
            if os.path.isdir(candidate):
                return candidate
    try:
        spec = importlib_util.find_spec("rvc_python")
        origin = getattr(spec, "origin", "") if spec is not None else ""
        if origin:
            candidate = os.path.join(os.path.dirname(os.path.abspath(origin)), "base_model")
            if os.path.isdir(candidate):
                return candidate
    except (ImportError, ValueError):
        pass
    return None


def resolve_runtime_model(filename: str, paths=None) -> Optional[str]:
    base = runtime_base_model_dir(paths)
    if not base:
        return None
    candidate = os.path.join(base, filename)
    return candidate if os.path.isfile(candidate) else None


def pretrained_family(version: str, sample_rate: int) -> str:
    """40k e v1 usano la famiglia storica; v2 usa pretrained_v2."""
    if str(version).lower() == "v1" or int(sample_rate) == 40000:
        return "pretrained"
    return "pretrained_v2"


def pretrained_filenames(sample_rate: int, f0: bool) -> Dict[str, str]:
    sr = "%dk" % (int(sample_rate) // 1000)
    if f0:
        return {"g": "f0G%s.pth" % sr, "d": "f0D%s.pth" % sr}
    return {"g": "G%s.pth" % sr, "d": "D%s.pth" % sr}


def assets_dir(paths, settings) -> str:
    configured = str(getattr(settings.training, "assets_dir", "") or "").strip()
    return configured or os.path.join(paths.training_dir, "assets")


def pretrained_dirs(paths, settings, family: str) -> List[str]:
    ordered: List[str] = []
    configured = str(getattr(settings.training, "pretrained_dir", "") or "").strip()
    if configured:
        ordered.append(configured)
        ordered.append(os.path.join(configured, family))
    base = assets_dir(paths, settings)
    ordered.append(os.path.join(base, family))
    ordered.append(base)
    for known in KNOWN_LOCAL_DIRS:
        ordered.append(os.path.join(known, family))
        ordered.append(known)
    seen: List[str] = []
    for directory in ordered:
        if directory and directory not in seen:
            seen.append(directory)
    return seen


def find_pretrained(paths, settings, sample_rate: int, f0: bool, version: str) -> Dict[str, Any]:
    family = pretrained_family(version, sample_rate)
    names = pretrained_filenames(sample_rate, f0)
    directories = pretrained_dirs(paths, settings, family)
    found: Dict[str, str] = {}
    for key, filename in names.items():
        for directory in directories:
            candidate = os.path.join(directory, filename)
            if os.path.isfile(candidate):
                found[key] = candidate
                break
    missing = [filename for key, filename in names.items() if key not in found]
    return {
        "family": family,
        "filenames": names,
        "found": found,
        "missing": missing,
        "dirs": directories,
        "complete": not missing,
    }


def _download(url: str, destination: str, on_log: Optional[Progress] = None) -> None:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    partial = destination + ".part"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if on_log:
        on_log("Download %s" % os.path.basename(destination))
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if on_log and total:
                on_log(
                    "%s: %d%%" % (os.path.basename(destination), int(done * 100 / total))
                )
    os.replace(partial, destination)


def ensure_pretrained(
    paths,
    settings,
    sample_rate: int,
    f0: bool,
    version: str,
    on_log: Optional[Progress] = None,
) -> Dict[str, Any]:
    """Restituisce i percorsi G/D, scaricandoli se mancano e il download e' permesso."""
    info = find_pretrained(paths, settings, sample_rate, f0, version)
    if info["complete"]:
        return info

    if not bool(getattr(settings.training, "auto_download_assets", True)):
        return info

    target_dir = os.path.join(assets_dir(paths, settings), info["family"])
    for key, filename in info["filenames"].items():
        if key in info["found"]:
            continue
        url = "%s/%s/%s" % (HF_BASE, info["family"], filename)
        destination = os.path.join(target_dir, filename)
        try:
            _download(url, destination, on_log=on_log)
            info["found"][key] = destination
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if on_log:
                on_log("Download fallito per %s: %s" % (filename, exc))
            continue
    info["missing"] = [
        filename
        for key, filename in info["filenames"].items()
        if key not in info["found"]
    ]
    info["complete"] = not info["missing"]
    return info


def assets_status(paths, settings, sample_rate: int, f0: bool, version: str) -> Dict[str, Any]:
    hubert = resolve_runtime_model("hubert_base.pt", paths)
    rmvpe = resolve_runtime_model("rmvpe.pt", paths)
    pretrained = find_pretrained(paths, settings, sample_rate, f0, version)
    issues: List[str] = []
    if not hubert:
        issues.append("hubert_base.pt assente nel runtime")
    if not rmvpe:
        issues.append("rmvpe.pt assente nel runtime")
    if not pretrained["complete"]:
        issues.append(
            "Pesi pre-addestrati mancanti: %s" % ", ".join(pretrained["missing"])
        )
    return {
        "hubert": hubert,
        "rmvpe": rmvpe,
        "pretrained": pretrained,
        "issues": issues,
        "ready": not issues,
    }
