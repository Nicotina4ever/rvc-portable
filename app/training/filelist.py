"""Costruzione di ``filelist.txt`` per il trainer.

Il trainer upstream si aspetta righe
``gt_wav|feature|f0|f0nsf|speaker``. Le righe "mute" aggiungono due campioni di
silenzio pre-calcolati: servono a stabilizzare le prime epoche e sono parte
della ricetta RVC.
"""

from __future__ import annotations

import os
from typing import Dict, List


def _names(directory: str, extension: str = ".wav") -> List[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(
        name[: -len(extension)]
        for name in os.listdir(directory)
        if name.lower().endswith(extension)
    )


def _mixed(path: str) -> str:
    """Percorso in forma accettata da Windows e POSIX."""
    return os.path.abspath(path).replace("\\", "/")


def build_filelist(
    exp_dir: str,
    version: str,
    f0: bool,
    mute_dir: str,
    sample_rate: int,
) -> Dict[str, object]:
    gt_dir = os.path.join(exp_dir, "0_gt_wavs")
    feature_dir = os.path.join(
        exp_dir, "3_feature256" if version == "v1" else "3_feature768"
    )
    f0_dir = os.path.join(exp_dir, "2a_f0")
    f0nsf_dir = os.path.join(exp_dir, "2b-f0nsf")

    names = set(_names(gt_dir)) & set(_names(feature_dir, ".npy"))
    if f0:
        names = names & set(_names(f0_dir, ".npy")) & set(_names(f0nsf_dir, ".npy"))
    if not names:
        raise ValueError(
            "nessun file completo: controlla preprocess, F0 e HuBERT prima del training"
        )

    lines: List[str] = []
    for name in sorted(names):
        if f0:
            lines.append(
                "%s|%s|%s|%s|0"
                % (
                    _mixed(os.path.join(gt_dir, name + ".wav")),
                    _mixed(os.path.join(feature_dir, name + ".npy")),
                    _mixed(os.path.join(f0_dir, name + ".npy")),
                    _mixed(os.path.join(f0nsf_dir, name + ".npy")),
                )
            )
        else:
            lines.append(
                "%s|%s|0"
                % (
                    _mixed(os.path.join(gt_dir, name + ".wav")),
                    _mixed(os.path.join(feature_dir, name + ".npy")),
                )
            )

    mute_lines = _mute_lines(mute_dir, version, f0, sample_rate)
    lines.extend(mute_lines * 2)

    target = os.path.join(exp_dir, "filelist.txt")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return {"path": target, "entries": len(names), "mute": len(mute_lines) * 2}


def _mute_lines(mute_dir: str, version: str, f0: bool, sample_rate: int) -> List[str]:
    if not mute_dir or not os.path.isdir(mute_dir):
        return []
    sr_name = "mute%dk.wav" % (int(sample_rate) // 1000)
    gt = os.path.join(mute_dir, "0_gt_wavs", sr_name)
    feature = os.path.join(
        mute_dir,
        "3_feature256" if version == "v1" else "3_feature768",
        "mute.npy",
    )
    f0_path = os.path.join(mute_dir, "2a_f0", "mute.wav.npy")
    f0nsf_path = os.path.join(mute_dir, "2b-f0nsf", "mute.wav.npy")
    if f0:
        if not all(os.path.isfile(path) for path in (gt, feature, f0_path, f0nsf_path)):
            return []
        return ["%s|%s|%s|%s|0" % (_mixed(gt), _mixed(feature), _mixed(f0_path), _mixed(f0nsf_path))]
    if not all(os.path.isfile(path) for path in (gt, feature)):
        return []
    return ["%s|%s|0" % (_mixed(gt), _mixed(feature))]
