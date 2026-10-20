"""Streaming audio con supporto Range (seek del player nella UI)."""

from __future__ import annotations

import os
import re
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

CHUNK_SIZE = 64 * 1024
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def media_type_for(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    return {
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".opus": "audio/ogg",
    }.get(extension, "application/octet-stream")


def range_response(request: Request, path: str, filename: Optional[str] = None):
    """Restituisce 200 o 206 con Content-Range, senza caricare il file in RAM."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    file_size = os.path.getsize(path)
    range_header = request.headers.get("range") or request.headers.get("Range")
    content_type = media_type_for(path)
    disposition = 'inline; filename="%s"' % (filename or os.path.basename(path)).replace('"', "")

    start = 0
    end = file_size - 1
    status = 200

    if range_header:
        match = _RANGE_RE.match(range_header.strip())
        if not match:
            return _unsatisfiable(file_size)
        raw_start, raw_end = match.groups()
        if raw_start:
            start = int(raw_start)
        if raw_end:
            end = int(raw_end)
        elif not raw_start:
            # "bytes=-N": ultimi N byte
            length = int(raw_end or 0)
            start = max(0, file_size - length)
            end = file_size - 1
        if start > end or start >= file_size:
            return _unsatisfiable(file_size)
        end = min(end, file_size - 1)
        status = 206

    length = max(0, end - start + 1)

    def iterator():
        remaining = length
        with open(path, "rb") as handle:
            handle.seek(start)
            while remaining > 0:
                block = handle.read(min(CHUNK_SIZE, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": disposition,
    }
    if status == 206:
        headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, file_size)

    return StreamingResponse(
        iterator(), status_code=status, media_type=content_type, headers=headers
    )


def _unsatisfiable(file_size: int):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=416,
        content={"error": {"code": "range_not_satisfiable", "message": "Range non valido"}},
        headers={"Content-Range": "bytes */%d" % file_size},
    )
