"""Rotte dell'addestramento RVC.

- ``GET  /api/training``              capacita' (CUDA, pesi, preset) + job
- ``POST /api/training/analyze``      analizza un dataset senza avviare nulla
- ``POST /api/training``              accoda un job di training
- ``GET  /api/training/{id}``         stato del job
- ``GET  /api/training/{id}/log``     coda del log
- ``POST /api/training/{id}/cancel``  annulla
- ``POST /api/training/{id}/resume``  riprende un job fallito
- ``POST /api/training/{id}/test``    converte un sample con il modello appena creato
- ``DELETE /api/training/{id}``       rimuove il job e i file intermedi
"""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Request

from ...core.engine import InferParams
from ...training import dataset as dataset_module
from ...training.manager import TrainingError
from .. import deps
from ..errors import ApiError

router = APIRouter(tags=["training"])

_STATUS_BY_CODE = {
    "training_not_found": 404,
    "training_disabled": 409,
    "training_busy": 409,
    "training_source_missing": 422,
    "training_dataset_invalid": 422,
    "training_assets_missing": 422,
    "training_settings_invalid": 422,
    "training_disk_low": 507,
    "training_resume_invalid": 409,
    "training_not_resumable": 409,
    "training_config_missing": 500,
    "training_output_missing": 500,
    "training_stage_failed": 500,
    "training_canceled": 409,
}


def _service(request: Request):
    service = getattr(request.app.state, "training_service", None)
    if service is None:
        raise ApiError("training_disabled", "Servizio di addestramento non inizializzato", 503)
    return service


def _raise(exc: TrainingError):
    raise ApiError(exc.code, exc.message, _STATUS_BY_CODE.get(exc.code, 400))


@router.get("/api/training")
def training_status(request: Request):
    service = _service(request)
    try:
        capabilities = service.capabilities()
    except Exception as exc:  # pragma: no cover - difensivo
        raise ApiError("internal_error", "Stato addestramento non disponibile", 500, {}, str(exc))
    return {"capabilities": capabilities, "jobs": service.list_jobs()}


@router.post("/api/training/analyze")
async def training_analyze(request: Request):
    body = await request.json()
    source = str((body or {}).get("source") or "").strip()
    if not source:
        raise ApiError("training_source_missing", "Indica una cartella o uno ZIP")
    try:
        report = dataset_module.inspect_source(source)
    except dataset_module.DatasetError as exc:
        raise ApiError("training_dataset_invalid", str(exc), 422)
    return {"report": report}


@router.post("/api/training")
async def training_start(request: Request):
    service = _service(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ApiError("training_settings_invalid", "Corpo JSON non valido")
    try:
        job = service.start(body)
    except TrainingError as exc:
        _raise(exc)
    return {"job": job, "jobs": service.list_jobs()}


@router.post("/api/training/{job_id}/cleanup")
def training_cleanup(job_id: str, request: Request):
    service = _service(request)
    try:
        result = service.clean_job_cache(job_id)
    except TrainingError as exc:
        _raise(exc)
    return {"job": result.get("job"), "freed_mb": result.get("freed_mb", 0)}


@router.post("/api/training/cleanup")
def training_cleanup_all(request: Request):
    service = _service(request)
    return service.clean_terminal_caches()


@router.get("/api/training/{job_id}")
def training_job(job_id: str, request: Request):
    service = _service(request)
    job = service.get_job(job_id)
    if job is None:
        raise ApiError("training_not_found", "Job di training non trovato", 404)
    return {"job": job}


@router.get("/api/training/{job_id}/log")
def training_log(job_id: str, request: Request, offset: int = 0, limit: int = 200):
    service = _service(request)
    try:
        return service.log_tail(job_id, offset=max(0, int(offset)), limit=max(1, min(2000, int(limit))))
    except TrainingError as exc:
        _raise(exc)


@router.post("/api/training/{job_id}/cancel")
def training_cancel(job_id: str, request: Request):
    service = _service(request)
    try:
        return {"job": service.cancel(job_id)}
    except TrainingError as exc:
        _raise(exc)


@router.post("/api/training/{job_id}/resume")
async def training_resume(job_id: str, request: Request):
    service = _service(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    add_epochs = int((body or {}).get("add_epochs") or 0)
    try:
        return {"job": service.resume(job_id, add_epochs=add_epochs)}
    except TrainingError as exc:
        _raise(exc)


@router.post("/api/training/{job_id}/test")
async def training_test(job_id: str, request: Request):
    service = _service(request)
    job = service.get_job(job_id)
    if job is None:
        raise ApiError("training_not_found", "Job di training non trovato", 404)
    if job.get("status") != "completed":
        raise ApiError("training_test_invalid", "Il modello non e' ancora pronto", 409)
    output = job.get("output") or {}
    model_path = str(output.get("model") or "")
    if not os.path.isfile(model_path):
        raise ApiError("model_not_found", "Modello prodotto non trovato su disco", 404)

    body = await request.json() if request.headers.get("content-length") not in (None, "0") else {}
    sample = str((body or {}).get("sample") or "").strip()
    if not sample:
        raw_dir = os.path.join(job["dir"], "dataset", "raw")
        candidates = sorted(
            os.path.join(raw_dir, name)
            for name in os.listdir(raw_dir)
            if os.path.isfile(os.path.join(raw_dir, name))
        )
        sample = candidates[0] if candidates else ""
    if not sample or not os.path.isfile(sample):
        raise ApiError("input_missing", "Nessun sample disponibile per il test", 404)

    settings = deps.settings_manager(request).settings
    if not settings.audio.output_dir:
        raise ApiError("output_dir_missing", "Configura una cartella output prima del test", 422)

    job_settings = job.get("settings") or {}
    params = InferParams(
        pitch=0,
        method="rmvpe",
        protect=0.33,
        index_rate=0.3,
        filter_radius=3,
        rms_mix_rate=0.25,
        resample_sr=0,
        model_version=str(job_settings.get("version") or "v2"),
        output_format="wav",
    )
    try:
        queued = deps.jobs(request).enqueue(
            sample,
            params,
            model_path=model_path,
            index_path=str(output.get("index") or ""),
            source="training_test",
        )
    except Exception as exc:
        raise ApiError("engine_unavailable", "Impossibile accodare il test", 503, {}, str(exc))
    return {"job_id": queued.id, "sample": sample}


@router.delete("/api/training/{job_id}")
def training_delete(job_id: str, request: Request):
    service = _service(request)
    job = service.get_job(job_id)
    if job is None:
        raise ApiError("training_not_found", "Job di training non trovato", 404)
    if job.get("status") in ("running", "queued"):
        raise ApiError("job_running", "Annulla il job prima di eliminarlo", 409)
    job_dir = str(job.get("dir") or "")
    if job_dir and os.path.isdir(job_dir):
        shutil.rmtree(job_dir, ignore_errors=True)
    with service._lock:  # noqa: SLF001 - operazione interna amministrativa
        service._jobs.pop(job_id, None)
        try:
            service._order.remove(job_id)
        except ValueError:
            pass
        service._save()
    return {"deleted": job_id}
