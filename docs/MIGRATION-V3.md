# Migrazione dalla 2.x alla 3.0

La 3.0 cambia architettura (GUI → backend + web) ma **non tocca i tuoi modelli** e migra la
configurazione in automatico. Nessun file viene cancellato: ciò che non serve viene spostato in
`da_eliminare/` (ripristinabile).

## 1. Cosa cambia per l'utente

| Prima (2.x) | Dopo (3.0) |
|---|---|
| `Avvia-RVC.bat` / `run.bat` (GUI CustomTkinter) | `run.bat` (finestra app, nessuna console) |
| `config_gui.py`, `Avvia-RVC-config-cloud.bat` | UI unica con tab Configurazione/Cloud |
| `config.json` piatto nella root | `data/config.json` schema v3 |
| `lang/*.json` | `locales/{it,en}.json` (usati anche dal backend) |
| Dropbox SDK + App Key fissa | client PKCE con la **tua** App Key |
| Monitor solo in finestra CMD | monitor integrato con coda e log live |

## 2. Migrazione automatica della configurazione

Al primo avvio:

1. se `data/config.json` non esiste e trova il vecchio `config.json` nella root, lo legge;
2. converte i campi piatti nello schema v3;
3. normalizza i valori non più supportati:
   - `method: "fcpe"` → `"rmvpe"` (con warning);
   - `device: "dml:0"` → `"auto"` (con warning);
   - `cloud_config_path` → `cloud.local_path`;
   - `auto_reload_cloud` → `cloud.hot_reload`;
   - `dropbox_app_key` → `cloud.dropbox.app_key`;
4. salva in `data/config.json` (con backup `.bak`) e lascia l'originale in quarantena.

Tabella campi:

| v2 | v3 |
|---|---|
| `input_dir` | `audio.input_dir` |
| `output_dir` | `audio.output_dir` |
| `model_path` | `audio.model_path` |
| `index_path` | `audio.index_path` |
| `pitch` | `audio.pitch` |
| `method` | `audio.method` |
| `protect` | `audio.protect` |
| `index_rate` | `audio.index_rate` |
| `device` | `engine.device` |
| `language` | `ui.language` |
| `cloud_config_path` | `cloud.local_path` |
| `auto_reload_cloud` | `cloud.hot_reload` |
| `dropbox_app_key` | `cloud.dropbox.app_key` |

Nuovi campi: `audio.{model_version, filter_radius, rms_mix_rate, resample_sr, output_format}`,
`engine.{warm_model, idle_unload_minutes}`, `monitor.*`, `ui.{theme,last_view}`.

## 3. Runtime (importante)

La 2.x tentava Python 3.12: **il motore RVC non funziona su 3.12** (pin di numpy/fairseq e
`torch.load`). La 3.0 usa il runtime verificato:

- Windows: Python 3.9.13 + torch 2.0.0+cu118 + rvc-python 0.1.5 + fairseq 0.12.2 (scaricato al primo setup);
- macOS/Linux: Python 3.10 + torch 2.2.2 + stessi pin (creato da `tools/bootstrap.py`).

Il vecchio `runtime/` 3.12 è in `da_eliminare/runtime-python312-windows/`.

## 4. Dove sono finiti i file

| File | Destinazione |
|---|---|
| `app.py`, `rvc_engine.py`, `config_manager.py`, `cloud_sync.py`, `file_monitor.py`, `i18n.py`, `setup_wizard.py` | `da_eliminare/versione-2.0/` |
| `lang/` | `da_eliminare/versione-2.0/lang/` |
| `config.json` (originale) | `da_eliminare/versione-2.0/config.json` |
| `Backup/`, `Test/`, `legacy/` | `da_eliminare/` |
| Vecchie distribuzioni | `da_eliminare/distribuzioni-precedenti/` |
| `Note.txt`, `Per Index Replay.txt`, `walkthrough.md`, piano v2 | `docs/` (archivio e guide) |

Inventario completo: [../da_eliminare/INVENTARIO.md](../da_eliminare/INVENTARIO.md).

## 5. Rollback

Hai due livelli di sicurezza:

1. **Codice 2.x**: `da_eliminare/_snapshot-pre-3.0/` contiene i moduli e i launcher originali.
2. **File spostati**: `python tools/quarantine.py --restore` li riporta al loro posto
   (`--only <id>` per singole voci).
3. **Runtime 3.12**: in `da_eliminare/runtime-python312-windows/` (il motore però non funzionava).

## 6. Dopo la migrazione

1. Apri **Avanzate → Diagnostica**: tutti i check verdi (in particolare `engine`, `torch`, `base_models`).
2. Controlla i percorsi in **Configurazione** (le vecchie unità `J:\` devono essere raggiungibili).
3. In **Cloud** reinserisci la App Key Dropbox se usavi OAuth.
4. Prova una conversione con un file breve e verifica l'output.
5. Se tutto ok, puoi svuotare `da_eliminare/` quando vuoi (nessun file serve all'app).
