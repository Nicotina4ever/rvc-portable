"""Comandi di sviluppo (test, lint, doctor, serve, verifica i18n/JS/repository).

Uso:
    runtime\\python.exe -B tools\\dev.py test
    runtime\\python.exe -B tools\\dev.py lint
    runtime\\python.exe -B tools\\dev.py doctor
    runtime\\python.exe -B tools\\dev.py serve --console
    runtime\\python.exe -B tools\\dev.py check-web
    runtime\\python.exe -B tools\\dev.py check-repo
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = os.name == "nt"
DEV_DIR = os.path.join(ROOT, ".dev", "site-packages")
RUNTIME_PY = (
    os.path.join(ROOT, "runtime", "python.exe")
    if IS_WINDOWS
    else os.path.join(ROOT, "runtime", "bin", "python3")
)


def python() -> str:
    if os.path.isfile(RUNTIME_PY):
        return RUNTIME_PY
    return sys.executable


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run(cmd, check=True) -> int:
    print("$ " + " ".join(cmd), flush=True)
    code = subprocess.run(cmd, cwd=ROOT, env=_env()).returncode
    if check and code != 0:
        print("comando fallito: %d" % code)
    return code


def ensure_dev() -> bool:
    if not os.path.isdir(DEV_DIR):
        print("Strumenti di sviluppo assenti: esegui tools/bootstrap.py --dev")
        return False
    return True


def cmd_test(args) -> int:
    if not ensure_dev():
        return 2
    cmd = [python(), "-B", "-m", "pytest", "tests", "-q"]
    if args.extra:
        cmd += args.extra
    return run(cmd, check=False)


def cmd_lint(args) -> int:
    if not ensure_dev():
        return 2
    cmd = [python(), "-B", "-m", "ruff", "check", "app", "tests", "tools"]
    if args.fix:
        cmd.append("--fix")
    return run(cmd, check=False)


def cmd_doctor(args) -> int:
    return run([python(), "-B", "-m", "app", "--doctor"], check=False)


def cmd_serve(args) -> int:
    cmd = [python(), "-B", "launch.py", "--console"]
    if args.extra:
        cmd += args.extra
    return run(cmd, check=False)


def cmd_check_web(args) -> int:
    node = shutil.which("node")
    if not node:
        print("Node non disponibile: salto la verifica sintattica JS.")
        return 0
    failures = 0
    js_root = os.path.join(ROOT, "web", "js")
    for base, _dirs, files in os.walk(js_root):
        for name in files:
            if not name.endswith(".js"):
                continue
            source = os.path.join(base, name)
            with tempfile.NamedTemporaryFile(
                "w", suffix=".mjs", delete=False, encoding="utf-8"
            ) as tmp:
                with open(source, "r", encoding="utf-8") as handle:
                    tmp.write(handle.read())
                tmp_path = tmp.name
            try:
                code = subprocess.run(
                    [node, "--check", tmp_path], capture_output=True, text=True
                ).returncode
            finally:
                os.unlink(tmp_path)
            status = "OK" if code == 0 else "ERRORE"
            print("%-6s %s" % (status, os.path.relpath(source, ROOT)))
            failures += 0 if code == 0 else 1
    return 0 if failures == 0 else 1


def cmd_i18n(args) -> int:
    locales = os.path.join(ROOT, "locales")
    try:
        sys.path.insert(0, ROOT)
        from app.i18n import validate_catalogs

        problems = validate_catalogs(locales)
    except Exception as exc:  # pragma: no cover
        print("impossibile validare i cataloghi: %s" % exc)
        return 1
    if problems:
        for problem in problems:
            print("ERRORE: %s" % problem)
        return 1
    print("Cataloghi i18n coerenti.")
    return 0


def cmd_restore(args) -> int:
    return run(
        [
            python(),
            "-B",
            os.path.join(ROOT, "tools", "restore_runtime_windows.py"),
            "--dest",
            args.dest,
        ]
        + (["--force"] if args.force else [])
    )


def cmd_check_repo(args) -> int:
    return run(
        [python(), "-B", os.path.join(ROOT, "tools", "check_repo.py")]
        + (["--json"] if args.json else []),
        check=False,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Comandi di sviluppo RVC Portable")
    sub = parser.add_subparsers(dest="command", required=True)

    test = sub.add_parser("test")
    test.add_argument("extra", nargs="*", help="argomenti extra per pytest")
    test.set_defaults(func=cmd_test)

    lint = sub.add_parser("lint")
    lint.add_argument("--fix", action="store_true")
    lint.set_defaults(func=cmd_lint)

    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    serve = sub.add_parser("serve")
    serve.add_argument("extra", nargs="*", help="argomenti extra per launch.py")
    serve.set_defaults(func=cmd_serve)

    web = sub.add_parser("check-web")
    web.set_defaults(func=cmd_check_web)

    i18n = sub.add_parser("i18n")
    i18n.set_defaults(func=cmd_i18n)

    restore = sub.add_parser("restore-runtime")
    restore.add_argument("--dest", default="runtime")
    restore.add_argument("--force", action="store_true")
    restore.set_defaults(func=cmd_restore)

    repo = sub.add_parser("check-repo")
    repo.add_argument("--json", action="store_true")
    repo.set_defaults(func=cmd_check_repo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
