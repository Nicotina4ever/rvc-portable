"""Rotte job: coda, stato, annullamento, audio e waveform."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Request

from ... import events
from ...core.audio import waveform_peaks
from ...core.engine import InferParams
from .. import deps
from ..audio import range_response
from ..errors import ApiError

router = APIRouter(tags=["jobs"])

PARAM_KEYS = (
    "pitch",
    "method",
    "protect",
    "index_rate",
    "filter_radius",
    "rms_mix_rate",
    "resample_sr",
    "model_version",
    "output_format",
)


def _build_params(request: Request, overrides: Dict[str, Any]) -> InferParams:
    settings = deps.settings_manager(request).settings
    params = InferParams.from_audio(settings.audio).to_dict()
    for key in PARAM_KEYS:
        if key in (overrides or {}) and overrides[key] is not None:
            params[key] = overrides[key]
    try:
        return InferParams(**params)
    except TypeError as exc:
        raise ApiError("validation_error", "Parametri non validi", 422, {}, str(exc))


def _job_payload(job) -> Dict[str, Any]:
    return job.to_dict()


def _get_job(request: Request, job_id: str):
    job = deps.jobs(request).get(job_id)
    if job is None:
        raise ApiError("job_not_found", "Job non trovato", 404, {"job_id": job_id})
    return job


@router.post("/api/jobs/batch")
async def enqueue_batch(request: Request):
    body = await request.json()
    inputs = body.get("inputs") or []
    if not isinstance(inputs, list) or not inputs:
        raise ApiError("validation_error", "Serve una lista 'inputs' non vuota")
    queue = deps.jobs(request)
    model = str(body.get("model") or "")
    index = str(body.get("index") or "")
    params = _build_params(request, body.get("params") or {})
    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for item in inputs:
        try:
            job = queue.enqueue(
                str(item),
                params,
                model_path=model,
                index_path=index,
                source="manual",
            )
            created.append(_job_payload(job))
        except FileNotFoundError as exc:
            skipped.append({"path": str(item), "reason": "file non trovato: %s" % exc})
        except (ValueError, OSError) as exc:
            skipped.append({"path": str(item), "reason": str(exc)})
    return {"jobs": created, "skipped": skipped}


@router.post("/api/jobs/clear")
def clear_jobs(request: Request):
    removed = deps.jobs(request).clear_finished()
    return {"removed": removed}


@router.get("/api/jobs")
def list_jobs(request: Request, limit: int = 50, include_terminal: bool = True):
    queue = deps.jobs(request)
    jobs = queue.list(limit=limit, include_terminal=include_terminal)
    return {
        "jobs": [_job_payload(job) for job in jobs],
        "stats": queue.stats(),
        "current": queue.current_job_id,
    }


@router.post("/api/jobs")
async def enqueue(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ApiError("validation_error", "Corpo JSON non valido")
    input_path = str(body.get("input") or body.get("input_path") or "").strip()
    if not input_path:
        raise ApiError("validation_error", "Campo 'input' obbligatorio")
    params = _build_params(request, body.get("params") or {})
    queue = deps.jobs(request)
    try:
        job = queue.enqueue(
            input_path,
            params,
            model_path=str(body.get("model") or ""),
            index_path=str(body.get("index") or ""),
            source=str(body.get("source") or "manual"),
            output_dir=str(body.get("output_dir") or ""),
            dedupe=bool(body.get("dedupe", True)),
        )
    except FileNotFoundError as exc:
        code = "input_missing" if str(exc) == input_path else "model_not_found"
        raise ApiError(code, "File non trovato", 404, {"path": str(exc)})
    except OSError as exc:
        raise ApiError("output_dir_missing", "Cartella output non valida", 422, {}, str(exc))
    except ValueError as exc:
        raise ApiError("validation_error", str(exc), 422)
    return _job_payload(job)


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    return _job_payload(_get_job(request, job_id))


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    job = deps.jobs(request).cancel(job_id)
    if job is None:
        raise ApiError("job_not_found", "Job non trovato", 404, {"job_id": job_id})
    return _job_payload(job)


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, request: Request):
    queue = deps.jobs(request)
    job = queue.get(job_id)
    if job is None:
        raise ApiError("job_not_found", "Job non trovato", 404, {"job_id": job_id})
    if job.state == "running":
        queue.cancel(job_id)
        return {"canceled": True, "removed": False}
    removed = queue.remove(job_id)
    return {"canceled": False, "removed": removed}


@router.get("/api/jobs/{job_id}/audio/{side}")
def job_audio(job_id: str, side: str, request: Request):
    job = _get_job(request, job_id)
    if side == "input":
        path = job.input_path
    elif side == "output":
        path = job.output_path
    else:
        raise ApiError("validation_error", "side deve essere input oppure output")
    if not path or not os.path.isfile(path):
        raise ApiError("not_found", "File audio non disponibile", 404, {"path": path})
    return range_response(request, path)


@router.get("/api/jobs/{job_id}/waveform")
def job_waveform(job_id: str, request: Request, side: str = "output", buckets: int = 800):
    job = _get_job(request, job_id)
    path = job.output_path if side == "output" else job.input_path
    if not path or not os.path.isfile(path):
        path = job.input_path
    if not path or not os.path.isfile(path):
        raise ApiError("not_found", "File audio non disponibile", 404)
    try:
        return waveform_peaks(path, buckets=max(32, min(int(buckets), 4000)))
    except NotImplementedError:
        raise ApiError(
            "internal_error",
            "Waveform non ancora implementata (teammate A)",
            status_code=501,
        )
    except Exception as exc:
        events.publish("log", level="error", source="audio", message=str(exc))
        raise ApiError("internal_error", "Impossibile calcolare la waveform", 500, {}, str(exc))
