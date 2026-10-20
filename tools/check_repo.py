"""Controlli di igiene del repository prima della pubblicazione su GitHub.

Verifica che il repository resti leggero e senza file locali/pesanti:

    python tools/check_repo.py            # umano
    python tools/check_repo.py --json     # macchina

Controlla: file obbligatori, cartelle locali non versionate (runtime, Modelli, data,
da_eliminare, dist, .dev), file troppo grandi, pattern di segreti nei file di testo,
e la presenza di archiviati/modelli nell'indice git quando il repository esiste.

Exit 0 = ok, 1 = errori (bloccano il push), 2 = solo avvisi.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_FILES = [
    ".gitignore",
    ".gitattributes",
    "README.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "install.conf",
    "launch.py",
    "run.bat",
    "run-console.bat",
    "run.sh",
    "run.command",
    "setup.bat",
    "setup.sh",
    "web/index.html",
    "locales/it.json",
    "locales/en.json",
    "docs/INSTALL.md",
    "docs/PUBLISHING.md",
    "requirements/base.txt",
    "requirements/engine-windows.txt",
    "requirements/engine-posix.txt",
    "tools/bootstrap.py",
    "tools/build_runtime_asset.py",
]

# Cartelle/paths che non devono MAI finire nel repository git.
LOCAL_ONLY = [
    "runtime/",
    "Modelli/",
    "Progetto/",
    "data/",
    "da_eliminare/",
    "dist/",
    ".dev/",
    ".venv/",
    ".pytest_cache/",
    ".ruff_cache/",
    "__pycache__/",
]

# File troppo grandi per un repository git comodo (GitHub blocca > 100 MB).
MAX_FILE_MB = 8.0
MAX_TOTAL_MB = 40.0

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsl\.[A-Za-z0-9_-]{40,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}"),
    re.compile(r"""\brefresh_token\s*[:=]\s*["'][A-Za-z0-9_-]{20,}["']"""),
    re.compile(r"""\bAuthorization\s*[:=]\s*["']Bearer\s+[A-Za-z0-9._-]{30,}["']"""),
]

TEXT_SUFFIXES = {
    ".py", ".md", ".js", ".css", ".html", ".json", ".txt", ".bat", ".cmd",
    ".sh", ".command", ".toml", ".yml", ".yaml", ".conf", ".ini", ".cfg", ".editorconfig",
}


def _run_git(args) -> tuple:
    try:
        completed = subprocess.run(
            ["git"] + args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed


def is_git_repo() -> bool:
    return os.path.isdir(os.path.join(ROOT, ".git"))


def git_tracked_files():
    completed = _run_git(["ls-files", "-z"])
    if completed is None or completed.returncode != 0:
        return None
    return [item for item in completed.stdout.split("\0") if item]


def git_untracked_files():
    completed = _run_git(["ls-files", "-z", "--others", "--exclude-standard"])
    if completed is None or completed.returncode != 0:
        return None
    return [item for item in completed.stdout.split("\0") if item]


def check_required() -> list:
    missing = [path for path in REQUIRED_FILES if not os.path.isfile(os.path.join(ROOT, path))]
    return ["file obbligatorio mancante: %s" % path for path in missing]


def check_local_only(paths) -> list:
    errors = []
    for path in paths:
        normalized = path.replace("\\", "/")
        for prefix in LOCAL_ONLY:
            if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
                errors.append("path locale versionato: %s (escluso da git)" % path)
                break
    return errors


def check_sizes(paths) -> tuple:
    errors = []
    warnings = []
    total = 0.0
    for path in paths:
        full = os.path.join(ROOT, path)
        if not os.path.isfile(full):
            continue
        size_mb = os.path.getsize(full) / (1024.0 * 1024.0)
        total += size_mb
        if size_mb > MAX_FILE_MB:
            errors.append("file troppo grande (%.1f MB): %s" % (size_mb, path))
    if total > MAX_TOTAL_MB:
        errors.append("totale file versati troppo grande: %.1f MB (max %.0f)" % (total, MAX_TOTAL_MB))
    return errors, warnings, total


def secret_hits(paths) -> list:
    hits = []
    for path in paths:
        if os.path.splitext(path)[1].lower() not in TEXT_SUFFIXES:
            continue
        full = os.path.join(ROOT, path)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read(2_000_000)
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append("possibile segreto in %s (%s)" % (path, pattern.pattern[:32]))
    return hits


def _walk_fallback():
    skip = {
        ".git", "runtime", "Modelli", "Progetto", "data", "da_eliminare", "dist",
        ".dev", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__",
    }
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in sorted(names):
            full = os.path.join(base, name)
            yield os.path.relpath(full, ROOT).replace("\\", "/")


def collect() -> dict:
    report = {
        "git": is_git_repo(),
        "tracked": None,
        "untracked": 0,
        "errors": [],
        "warnings": [],
        "total_mb": 0.0,
    }
    report["errors"].extend(check_required())

    tracked = git_tracked_files() if report["git"] else None
    if tracked is None:
        candidates = list(_walk_fallback())
    else:
        report["tracked"] = len(tracked)
        untracked = git_untracked_files() or []
        report["untracked"] = len(untracked)
        candidates = list(dict.fromkeys(tracked + untracked))

    report["errors"].extend(check_local_only(candidates))
    size_errors, size_warnings, total = check_sizes(candidates)
    report["errors"].extend(size_errors)
    report["warnings"].extend(size_warnings)
    report["total_mb"] = round(total, 2)
    report["errors"].extend(secret_hits(candidates))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Controlli igiene repository GitHub")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = collect()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("RVC Portable — igiene repository")
        print("  git:            %s" % ("si" if report["git"] else "no (controllo filesystem)"))
        print("  file versionati: %s" % report["tracked"])
        print("  file in attesa:  %s" % report["untracked"])
        print("  dimensione:     %.2f MB" % report["total_mb"])
        if report["errors"]:
            print("\nERRORI:")
            for item in report["errors"]:
                print("  - %s" % item)
        if report["warnings"]:
            print("\nAVVISI:")
            for item in report["warnings"]:
                print("  - %s" % item)
        if not report["errors"]:
            print("\nOK: repository pronto per il push.")
    if report["errors"]:
        return 1
    return 2 if report["warnings"] else 0


if __name__ == "__main__":
    sys.exit(main())
