"""Crea l'asset del runtime Windows da pubblicare su GitHub Releases.

Il repository resta leggero (~3 MB): il runtime Python 3.9.13 con motore RVC
(~5,7 GB estratti, ~2,5 GB compressi) viene distribuito come asset separato della
release e scaricato da ``setup.bat`` al primo avvio.

GitHub limita ogni asset a 2 GiB: se lo zip supera il limite viene diviso in parti
(``.001``, ``.002``, ...) e ``setup.bat`` le ricompone prima di verificare l'hash.

Uso tipico (una volta, dopo aver creato il repository GitHub):

    runtime\\python.exe -B tools\\build_runtime_asset.py ^
        --repo TUO_UTENTE/rvc-portable --update-install-conf

Poi carica in una release (tag ``runtime-v3.0.0``) tutti i file elencati
in ``dist/<nome>.manifest.json`` e committa ``install.conf``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(ROOT, "runtime")
INSTALL_CONF = os.path.join(ROOT, "install.conf")
DEFAULT_NAME = "RVC-Portable-runtime-windows-py39-cu118.zip"
DEFAULT_TAG = "runtime-v3.0.0"
DEFAULT_PART_MB = 1900  # margine sotto il limite GitHub di 2 GiB per asset
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDE_FILES = {"zz_dev_site_packages.pth"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".tmp", ".log")


def iter_runtime_files(runtime: str = RUNTIME):
    """Elenca i file da includere, senza cache/dev (ordine stabile)."""
    for base, dirs, names in os.walk(runtime):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(names):
            if name in EXCLUDE_FILES or name.lower().endswith(EXCLUDE_SUFFIXES):
                continue
            yield os.path.join(base, name)


def check_runtime() -> bool:
    python = os.path.join(RUNTIME, "python.exe" if os.name == "nt" else "bin/python3")
    if not os.path.isfile(python):
        print("runtime/ non trovato o incompleto: %s" % RUNTIME)
        return False
    code = "import torch, rvc_python.infer, fastapi, soundfile; print('OK')"
    completed = subprocess.run(
        [python, "-B", "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    if completed.returncode != 0 or "OK" not in completed.stdout:
        print("verifica runtime FALLITA:\n%s" % (completed.stderr or completed.stdout)[-1200:])
        return False
    return True


def build_zip(destination: str, compresslevel: int = 1) -> dict:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = destination + ".part"
    if os.path.exists(temporary):
        os.remove(temporary)
    started = time.time()
    count = 0
    total = 0
    print("creazione %s ..." % os.path.basename(destination), flush=True)
    with zipfile.ZipFile(
        temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=compresslevel, allowZip64=True
    ) as archive:
        for index, path in enumerate(iter_runtime_files(), start=1):
            archive.write(path, os.path.join("runtime", os.path.relpath(path, RUNTIME)))
            count = index
            total += os.path.getsize(path)
            if index % 4000 == 0:
                print(
                    "  %d file, %d MB letti, %.0fs"
                    % (index, total // (1024 * 1024), time.time() - started),
                    flush=True,
                )
    os.replace(temporary, destination)
    digest = hashlib.sha256()
    with open(destination, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    sha256 = digest.hexdigest()
    with open(destination + ".sha256", "w", encoding="ascii") as handle:
        handle.write("%s  %s\n" % (sha256, os.path.basename(destination)))
    elapsed = time.time() - started
    result = {
        "path": destination,
        "name": os.path.basename(destination),
        "files": count,
        "sha256": sha256,
        "size_mb": round(os.path.getsize(destination) / (1024.0 * 1024.0), 1),
        "seconds": round(elapsed, 1),
    }
    print(
        "creato %(name)s: %(files)s file, %(size_mb).1f MB, sha256=%(sha256)s (%(seconds).0fs)"
        % result
    )
    return result


def split_archive(path: str, part_size_mb: int = DEFAULT_PART_MB) -> list:
    """Divide lo zip in parti da <= part_size_mb (GitHub: max 2 GiB per asset)."""
    part_size = max(1, int(part_size_mb)) * 1024 * 1024
    total = os.path.getsize(path)
    if total <= part_size:
        return [path]
    print(
        "zip di %.0f MB: divisione in parti da %d MB (limite GitHub 2 GiB)..."
        % (total / (1024.0 * 1024.0), part_size_mb),
        flush=True,
    )
    parts = []
    index = 1
    with open(path, "rb") as source:
        while True:
            first = source.read(min(8 * 1024 * 1024, part_size))
            if not first:
                break
            part_path = "%s.%03d" % (path, index)
            written = len(first)
            with open(part_path, "wb") as target:
                target.write(first)
                while written < part_size:
                    chunk = source.read(min(8 * 1024 * 1024, part_size - written))
                    if not chunk:
                        break
                    target.write(chunk)
                    written += len(chunk)
            parts.append(part_path)
            index += 1
    os.remove(path)
    total_part_mb = sum(os.path.getsize(item) for item in parts) / (1024.0 * 1024.0)
    print(
        "create %d parti (%.1f MB totali): %s"
        % (len(parts), total_part_mb, ", ".join(os.path.basename(item) for item in parts))
    )
    return parts


def update_install_conf(
    url: str, sha256: str, size_mb: float, parts: int = 1, path: str = INSTALL_CONF
) -> None:
    """Aggiorna URL/SHA/dimensione/parti in install.conf mantenendo commenti e ordine."""
    values = {
        "RUNTIME_WINDOWS_URL": url,
        "RUNTIME_WINDOWS_SHA256": sha256,
        "RUNTIME_WINDOWS_SIZE_MB": str(int(round(size_mb))),
        "RUNTIME_WINDOWS_PARTS": str(int(parts)),
    }
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    output = []
    seen = set()
    pattern = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=")
    for line in lines:
        match = pattern.match(line)
        if match and match.group(1) in values:
            key = match.group(1)
            output.append("%s=%s" % (key, values[key]))
            seen.add(key)
        else:
            output.append(line)
    for key in values:
        if key not in seen:
            output.append("%s=%s" % (key, values[key]))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(output) + "\n")
    try:
        shown = os.path.relpath(path, ROOT)
    except ValueError:  # unita' diversa (test su temp)
        shown = path
    print("aggiornato %s" % shown)


def parse_install_conf(path: str = INSTALL_CONF) -> dict:
    values = {}
    if not os.path.isfile(path):
        return values
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def existing_asset_info(output: str, name: str, url: str = "") -> dict:
    """Recupera SHA/dimensione/parti di un asset già creato (per --only-update-conf)."""
    manifest_path = os.path.join(output, name + ".manifest.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "sha256": data["sha256"],
            "size_mb": float(data.get("size_mb", 0)),
            "parts": int(data.get("parts", 1)),
            "url": url or data.get("url", ""),
        }
    sha_path = os.path.join(output, name + ".sha256")
    if not os.path.isfile(sha_path):
        raise SystemExit("asset esistente non trovato in %s: crea prima l'archivio" % output)
    with open(sha_path, "r", encoding="ascii") as handle:
        sha256 = handle.read().split()[0]
    parts = 1
    while os.path.isfile("%s.%03d" % (os.path.join(output, name), parts + 1)):
        parts += 1
    return {"sha256": sha256, "size_mb": 0.0, "parts": parts, "url": url}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crea l'asset runtime per GitHub Releases")
    parser.add_argument("--output", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--repo", default="", help="owner/repo GitHub (per l'URL della release)")
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--update-install-conf", action="store_true")
    parser.add_argument(
        "--only-update-conf",
        action="store_true",
        help="non ricostruisce l'asset: aggiorna solo l'URL in install.conf",
    )
    parser.add_argument("--skip-check", action="store_true")
    parser.add_argument("--compresslevel", type=int, default=1, choices=range(1, 10))
    parser.add_argument("--part-size-mb", type=int, default=DEFAULT_PART_MB)
    args = parser.parse_args(argv)

    if args.only_update_conf:
        if not args.repo:
            print("--only-update-conf richiede --repo owner/repo")
            return 2
        url = "https://github.com/%s/releases/download/%s/%s" % (
            args.repo.strip("/"),
            args.tag,
            args.name,
        )
        info = existing_asset_info(args.output, args.name, url)
        update_install_conf(url, info["sha256"], info["size_mb"], info["parts"])
        print("URL aggiornato. Carica nella release i file:")
        for index in range(1, info["parts"] + 1):
            print("  %s" % os.path.join(args.output, "%s.%03d" % (args.name, index)))
        return 0

    if not args.skip_check and not check_runtime():
        return 1
    destination = os.path.join(args.output, args.name)
    result = build_zip(destination, compresslevel=args.compresslevel)
    parts = split_archive(destination, part_size_mb=args.part_size_mb)

    url = ""
    if args.repo:
        if "/" not in args.repo:
            print("--repo deve essere nel formato owner/repo")
            return 2
        url = "https://github.com/%s/releases/download/%s/%s" % (
            args.repo.strip("/"),
            args.tag,
            args.name,
        )
    if args.update_install_conf:
        if not url:
            url = parse_install_conf().get("RUNTIME_WINDOWS_URL", "")
        update_install_conf(url, result["sha256"], result["size_mb"], len(parts))

    upload = [os.path.basename(item) for item in parts]
    manifest = {
        "name": args.name,
        "sha256": result["sha256"],
        "size_mb": result["size_mb"],
        "files": result["files"],
        "parts": len(parts),
        "upload": upload,
        "url": url,
    }
    manifest_path = os.path.join(args.output, args.name + ".manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    print("manifest: %s" % manifest_path)

    print("\nProssimi passi:")
    if url:
        print("  1. crea la release GitHub con tag %s" % args.tag)
        print("  2. carica questi asset nella release:")
        for name in upload:
            print("       %s" % os.path.join(args.output, name))
        print("     URL base: %s" % url)
    else:
        print("  1. ripeti con --repo owner/repo per generare l'URL della release")
        print("  2. carica gli asset elencati sopra nella release GitHub")
    print("  3. se non usi --update-install-conf, copia questi valori in install.conf:")
    print("       RUNTIME_WINDOWS_URL=<url base dell'asset>")
    print("       RUNTIME_WINDOWS_SHA256=%s" % result["sha256"])
    print("       RUNTIME_WINDOWS_SIZE_MB=%d" % int(round(result["size_mb"])))
    print("       RUNTIME_WINDOWS_PARTS=%d" % len(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
