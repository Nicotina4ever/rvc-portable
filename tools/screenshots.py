"""Cattura gli screenshot della UI con Edge/Chrome headless (per README e docs).

Richiede un backend gia' avviato (headless) sulla porta indicata.

    python tools/screenshots.py --base http://127.0.0.1:8771
    python tools/screenshots.py --base ... --views dashboard,config --lang en
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION = os.path.join(ROOT, "data", "state", "session.json")
OUT_DIR = os.path.join(ROOT, "docs", "img")
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def find_browser() -> str:
    for candidate in EDGE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    found = shutil.which("msedge") or shutil.which("google-chrome") or shutil.which("chromium")
    if not found:
        raise SystemExit("Browser headless non trovato (serve Edge o Chrome)")
    return found


def token_from_session() -> str:
    with open(SESSION, "r", encoding="utf-8") as handle:
        return json.load(handle)["token"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Screenshot UI RVC Portable")
    parser.add_argument("--base", default="http://127.0.0.1:8771")
    parser.add_argument("--views", default="dashboard,config,monitor,models,cloud,advanced")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--lang", choices=("it", "en"), default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--no-restore", action="store_true")
    args = parser.parse_args(argv)

    browser = find_browser()
    token = args.token or token_from_session()
    auth = {"Authorization": "Bearer %s" % token}
    os.makedirs(OUT_DIR, exist_ok=True)

    patch = {}
    if args.lang:
        patch["ui"] = {"language": args.lang}
    if patch:
        requests.patch(args.base + "/api/settings", json={"patch": patch}, headers=auth, timeout=10).raise_for_status()

    failures = 0
    for view in [name.strip() for name in args.views.split(",") if name.strip()]:
        requests.patch(
            args.base + "/api/settings",
            json={"patch": {"ui": {"last_view": view}}},
            headers=auth,
            timeout=10,
        ).raise_for_status()
        profile = tempfile.mkdtemp(prefix="rvc-shot-")
        target = os.path.join(OUT_DIR, "%s.png" % view)
        if os.path.exists(target):
            os.remove(target)
        url = "%s/?t=%s" % (args.base, token)
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--window-size=%d,%d" % (args.width, args.height),
            "--force-device-scale-factor=1",
            "--user-data-dir=%s" % profile,
            "--screenshot=%s" % target,
            url,
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        if not os.path.isfile(target) or os.path.getsize(target) < 5000:
            failures += 1
            print("ERRORE %s (exit %s): %s" % (view, completed.returncode, (completed.stderr or "")[-300:]))
        else:
            print("%-10s %6.1f KB  %s" % (view, os.path.getsize(target) / 1024.0, target))

    if not args.no_restore:
        requests.patch(
            args.base + "/api/settings",
            json={"patch": {"ui": {"last_view": "dashboard"}}},
            headers=auth,
            timeout=10,
        )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
