# API Contract — RVC Portable 3.0

Server locale su `127.0.0.1:<porta>` (porta casuale, salvata in `data/state/session.json`).
Tutte le richieste `/api/*` richiedono il token di sessione:

```
Authorization: Bearer <token>
```

In alternativa `?t=<token>` (usato da `EventSource`, `<audio src>`, primo caricamento pagina).
Il token viene rimosso dalla URL dal frontend con `history.replaceState`.

Errori (envelope unico):

```json
{ "error": { "code": "settings_invalid", "message": "…", "params": {}, "detail": "…" } }
```

Codici: `unauthorized`, `forbidden_origin`, `forbidden_host`, `not_found`, `validation_error`,
`settings_invalid`, `settings_write_failed`, `engine_unavailable`, `engine_error`, `engine_busy`,
`model_invalid`, `model_not_found`, `index_invalid`, `input_missing`, `output_dir_missing`,
`job_not_found`, `job_running`, `monitor_error`, `cloud_error`, `dropbox_not_configured`,
`dropbox_invalid_client`, `dropbox_invalid_code`, `dropbox_conflict`, `network_error`, `internal_error`.

## Endpoint

| Metodo | Percorso | Request | Response |
|---|---|---|---|
| GET | `/api/health` | — | `{"status":"ok","version":"3.0.0","uptime_s":12.3}` (senza token) |
| GET | `/api/meta` | — | `{"app","version","python","platform","paths","engine": EngineStatus, "started_at"}` |
| GET | `/api/system/diagnostics?force=false` | — | `DoctorReport` |
| POST | `/api/system/shutdown` | — | `{"ok":true}` (spegnimento asincrono) |
| GET | `/api/settings` | — | `{"settings": Settings, "warnings": [str], "problems": [PathProblem], "config_path": str}` |
| PUT | `/api/settings` | `{"settings": Settings}` | come GET |
| PATCH | `/api/settings` | `{"patch": {…}}` (merge profondo) | come GET |
| GET | `/api/settings/export` | — | JSON scaricabile (`Content-Disposition: attachment`) |
| POST | `/api/settings/import` | `{"settings": {…}}` oppure corpo = oggetto Settings | come GET |
| POST | `/api/settings/reveal` | `{"target":"config|logs|data"}` | `{"path": "…"}` (apre nel file manager) |
| GET | `/api/hardware` | — | `{"probe": RuntimeProbe, "system": {...}, "devices": [DeviceOption]}` |
| GET | `/api/models` | — | `{"roots": [str], "models": [ModelEntry], "warnings": [str]}` |
| POST | `/api/models/scan` | `{"roots": [str]?}` | come GET |
| POST | `/api/models/probe` | `{"paths":[str]}` | `{"models":[ModelEntry]}` |
| POST | `/api/files/dialog` | `{"kind":"directory|model|index|audio|config","title":str,"initial":str}` | `{"path": str\|null, "canceled": bool}` |
| GET | `/api/jobs?limit=50&include_terminal=true` | — | `{"jobs":[Job], "stats": {...}, "current":"id\|null"}` |
| POST | `/api/jobs` | `{"input":str,"model":str?,"index":str?,"source":"manual","dedupe":bool,"params":{"pitch","method","protect","index_rate","filter_radius","rms_mix_rate","resample_sr","model_version","output_format"}}` | `Job` (201) |
| POST | `/api/jobs/batch` | `{"inputs":[str],"model":str?,"index":str?}` | `{"jobs":[Job], "skipped":[{"path","reason"}]}` |
| GET | `/api/jobs/{id}` | — | `Job` |
| DELETE | `/api/jobs/{id}` | — | `{"canceled":bool,"removed":bool}` |
| POST | `/api/jobs/{id}/cancel` | — | `Job` |
| POST | `/api/jobs/clear` | — | `{"removed": int}` |
| GET | `/api/jobs/{id}/audio/{side}` (`side=input\|output`) | Header `Range` opzionale | audio 200/206 con `Accept-Ranges` |
| GET | `/api/jobs/{id}/waveform?side=output&buckets=800` | — | `{"peaks":[…],"duration_s":x.1,"sample_rate":48000}` |
| GET | `/api/monitor` | — | `{"running":bool,"dir":str,"mode":str,"queued":int,"processed_session":int}` |
| POST | `/api/monitor/start` | `{"dir":str?,"process_existing":bool?}` | come GET |
| POST | `/api/monitor/stop` | — | come GET |
| POST | `/api/monitor/process-existing` | `{"dir":str?}` | `{"enqueued":int,"skipped":int}` |
| GET | `/api/cloud/dropbox` | — | `{"configured":bool,"connected":bool,"account":str\|null,"last_sync":ts\|null,"remote_path":str,"rev":str\|null}` |
| PUT | `/api/cloud/dropbox/key` | `{"app_key":str}` | come GET |
| POST | `/api/cloud/dropbox/authorize` | — | `{"auth_url":str,"expires_in_s":int}` |
| POST | `/api/cloud/dropbox/complete` | `{"code":str}` | come GET |
| POST | `/api/cloud/dropbox/upload` | `{"force":bool}` | `{"ok":bool,"rev":str,"message":str}` |
| POST | `/api/cloud/dropbox/download` | `{"force":bool}` | `{"ok":bool,"changed":bool,"message":str}` |
| DELETE | `/api/cloud/dropbox` | — | `{"ok":true}` (token rimosso) |
| GET | `/api/android` | — | `{"enabled","shared_dir","roots":[DropboxRoot],"paths":{…},"models_count","config_exists","models_exists","status_exists","pc_status":object,"config_sync":{…}}` |
| POST | `/api/android/detect` | — | `{"roots":[DropboxRoot],"suggested_shared_dir":str}` |
| POST | `/api/android/preset` | `{"shared_dir":str?}` | `{"ok":true,"summary":{…},"status": AndroidStatus}` (crea cartelle, `modelli.txt`, config; avvia il monitor) |
| POST | `/api/android/sync` | — | `{"ok":true,"summary":{"models":int,"paths":{…}}}` |
| POST | `/api/android/import` | — | `{"ok":true,"result":{"mode":"android|full","applied":[str],"skipped":[str]}}` |
| PUT | `/api/android/config` | payload piatto Android o Settings v3 | `{"ok":true,"result":{…}}` |
| GET | `/api/android/config` | — | `{"path":str,"payload":object\|null}` |
| GET | `/api/locales` | — | `{"languages":["it","en"],"default":"it"}` |
| GET | `/api/locales/{lang}` | — | `{"lang":"it","strings":{…}}` |
| GET | `/api/events?since=<id>` | — | `text/event-stream` |

Statici: `/` → `web/index.html`, `/css/*`, `/js/*`, `/assets/*`, `/locales/*`. Qualsiasi rotta non-API
sconosciuta restituisce `index.html` (SPA fallback).

## Oggetti

### Settings (schema v3)
```json
{
  "schema_version": 3,
  "audio": {
    "input_dir": "", "output_dir": "", "model_path": "", "index_path": "",
    "extra_model_dirs": [],
    "model_version": "v2", "pitch": 0, "method": "rmvpe", "protect": 0.33,
    "index_rate": 0.3, "filter_radius": 3, "rms_mix_rate": 0.25,
    "resample_sr": 0, "output_format": "wav"
  },
  "engine": { "device": "auto", "warm_model": true, "idle_unload_minutes": 15, "max_concurrency": 1 },
  "monitor": {
    "enabled_on_start": false, "process_existing": false, "watch_mode": "auto",
    "poll_interval_s": 2.0, "stability_ms": 1500,
    "ignore_globs": ["*.tmp","*.part","*.crdownload","~$*",".*"], "ignore_output_dir": true
  },
  "cloud": {
    "dropbox": { "app_key": "", "remote_path": "/NLTools/RVC/config.json" },
    "local_path": "", "hot_reload": false, "poll_interval_s": 3.0
  },
  "android": {
    "enabled": false, "shared_dir": "", "input_subdir": "AudioIn",
    "output_subdir": "AudioOut", "config_name": "config.json",
    "models_name": "modelli.txt", "status_name": "status.json",
    "status_heartbeat_s": 300.0,
    "apply_remote_config": true, "same_name_output": true
  },
  "ui": { "language": "it", "theme": "dark", "last_view": "dashboard", "compact": false }
}
```
Valori validi: `method ∈ {rmvpe,harvest,crepe,pm}`, `device ∈ {auto,cpu,cuda,cuda:N,mps}`,
`theme ∈ {dark,light,system}`, `output_format ∈ {wav,flac}`, `watch_mode ∈ {auto,native,polling}`.

Note ponte Android: con `android.enabled` e `same_name_output` attivi, i job con
`sorgente=monitor` scrivono `<output_dir>/<stesso nome input>.<ext>` (sovrascrivendo), così l'app
Android trova `AudioOut/<nome>.wav`. `ConfigSync` applica `cloud.local_path` (config v3 o piatto
Android) e riscrive la config in forma ibrida. Il PC pubblica `status.json` quando lo stato cambia
e con un heartbeat ogni `android.status_heartbeat_s` secondi (default 300) per il controllo remoto
dall'app (motore, coda, watcher, ultima config, parametri audio); `config.json` viene riscritto solo
se il contenuto cambia davvero.
Vedi [ANDROID-BRIDGE.md](ANDROID-BRIDGE.md).

### Job
```json
{
  "id": "hex32", "input_path": "…", "output_path": "…", "basename": "voce.wav",
  "output_name": "voce.wav", "model_path": "…", "index_path": "…",
  "params": {…}, "source": "manual|monitor", "state": "queued|running|done|failed|canceled",
  "stage": "loading|extract|f0|features|synthesize|write|done|retry",
  "progress": 42.0, "created_at": 1.0, "started_at": 1.1, "finished_at": 2.2,
  "elapsed_s": 1.1, "duration_s": 8.4, "sample_rate": 48000,
  "error_code": "", "error_message": "", "detail": "", "retries": 0, "terminal": false
}
```

### EngineStatus
```json
{ "available": true, "code": "", "message": "", "device": "cuda:0", "requested_device": "auto",
  "model_path": "", "index_path": "", "model_version": "v2", "loaded": false,
  "warm": false, "busy": false, "extra": { "python": "3.9.13", "torch": "2.0.0+cu118" } }
```

### ModelEntry
```json
{ "name": "Nicola-Spot2", "path": "…/Nicola-Spot2.pth", "index_path": "…/added_….index",
  "size_mb": 57.6, "version_guess": "v2", "source": "Modelli", "has_index": true,
  "warnings": ["indice opzionale assente"], "mtime": 1.0 }
```

### DoctorReport
```json
{ "overall": "ok|warn|fail", "counts": {"ok":8,"warn":1,"fail":0,"info":2},
  "checks": [{"id":"engine","label":"…","status":"ok|warn|fail|info","detail":"…","fix":"…","params":{}}],
  "environment": { "app_version":"3.0.0", "platform":"win32", "system":{…}, "paths":{…}, "probe":{…} } }
```

## SSE (`GET /api/events`)

Ogni evento: `id: <n>\nevent: <type>\ndata: <json>\n\n`.
Riconnessione: il client passa `since=<lastEventId>`; il server rigioca lo storico disponibile.

Tipi: `hello` `{session, version, engine}` · `log` `{ts,level,source,message,code?,params?}` ·
`job` `{Job}` · `job_log` `{job_id,message}` · `monitor` `{running,dir,mode}` ·
`config` `{source,path}` · `engine` `{EngineStatus}` · `toast` `{level,message_key,params}`.
Heartbeat: commento `: ping` ogni 15 s.

## Note di sicurezza
- `Host` deve essere `127.0.0.1|localhost|[::1]` (salvo `--allow-lan`).
- Metodi mutanti: `Origin` (se presente) deve essere `http://127.0.0.1:<porta>` e
  `Sec-Fetch-Site` deve essere `same-origin|none`.
- CSP: nessuno script inline, nessuna CDN. Le immagini possono essere `data:`.
- Nessun CORS: il frontend è servito dallo stesso origin.

## Contract interno (Python)

```python
class Engine(ABC):                    # app/core/engine.py
    def status(self) -> EngineStatus
    def load(self, model_path, index_path="", version="v2", device="auto") -> None
    def infer(self, input_path, output_path, params: InferParams,
              on_log=None, on_stage=None, is_cancelled=None) -> InferResult
    def cancel(self) -> None
    def unload(self) -> None
    def shutdown(self) -> None

class JobQueue:                       # app/core/jobs.py
    def start(self); def stop(self)
    def enqueue(self, input_path, params, model_path="", index_path="",
                source="manual", output_dir="", dedupe=True) -> Job
    def get(self, job_id) -> Job|None; def list(self, limit=50) -> list[Job]
    def cancel(self, job_id) -> Job|None; def remove(self, job_id) -> bool
    def stats(self) -> dict

class Watcher:                        # app/core/watcher.py (teammate A)
    def start(self, directory: str, process_existing: bool = False) -> dict
    def stop(self) -> dict
    def status(self) -> dict          # {"running","dir","mode","processed_session"}
    def process_existing(self, directory: str|None = None) -> dict  # {"enqueued","skipped"}

def scan_models(roots: list[str], default_index_hint: str = "") -> dict   # app/core/model_scan.py
def waveform_peaks(path: str, buckets: int = 800) -> dict                  # app/core/audio.py
def resolved_index_path(index_path: str, cache_dir: str) -> str           # app/core/index_shim.py
```

`app/api/app_factory.create_app()` espone su `app.state`:
`paths`, `settings_manager`, `engine`, `job_queue`, `watcher`, `bus`, `token`, `port`, `started_at`.
