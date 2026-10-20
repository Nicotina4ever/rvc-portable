# Pulizia e riordino — log

Operazioni di quarantena eseguite con `tools/quarantine.py` e `tools/trim_runtime.py`
(nessuna cancellazione: tutto è ripristinabile).

> Nota: `da_eliminare/` è una cartella **locale** e non è versionata (`.gitignore`); questo
> log resta come documentazione del riordino, ma chi clona il repository non trova i file
> in quarantena. Per versionare il progetto su GitHub bastano i sorgenti (~3 MB).

- 2026-10-20 — preparazione: snapshot del codice 2.0 in `da_eliminare/_snapshot-pre-3.0/`
  (31 file), manifest di integrità di `Modelli/` e `Progetto/Articolo Blog/` in
  `da_eliminare/_manifest-intoccabili-before.sha256` (25 file, 1.507,8 MB).
- 2026-10-20 — runtime: vecchio Python 3.12 (7,66 GB, motore assente) spostato in
  `da_eliminare/runtime-python312-windows/`; ripristinato il runtime Python 3.9.13 verificato
  da `Progetto/RVC-PortableConMonitoraggio.zip` (6,21 GB, 35.498 file).
- 2026-10-20 — gate motore: conversione reale su CUDA riuscita (RTX 4060 Ti, output 48 kHz,
  8,46 s, non silenzioso).
- 2026-10-20 — **apply quarantine**: 31 voci spostate, 0 errori.
  - codice 2.0 (`app.py`, `rvc_engine.py`, `config_manager.py`, `cloud_sync.py`, `file_monitor.py`,
    `i18n.py`, `setup_wizard.py`, `setup_hardware.bat`, `lang/`, `config.json`) → `da_eliminare/versione-2.0/`;
  - requirements obsoleti → `requirements-precedenti/`; `Readme.txt` → `documentazione-precedente/`;
  - `Backup`, `Test`, `legacy`, `Inserire nella cartella cloud` → `backup-2025`, `test-2025`,
    `legacy-2025`, `strumenti-obsoleti`;
  - vecchie distribuzioni (`00-Replay`, `01-RVC-Portable-MacOS`, zip Linux/macOS/Windows) →
    `distribuzioni-precedenti/` (≈5,5 GB);
  - `Progetto/Inviare Per MacOS/02 - Modello per Esperimenti Paolo` → `Modelli/Archivio/Paolo`
    (`.pth` identico, indice unico conservato); `Progetto/Inviare Per MacOS/` rimossa perché vuota.
  - Documenti storici già archiviati in `docs/archive/` (`walkthrough`, piano v2, note 2025);
    guide ancora valide in `docs/` (`GUIDA-INDEX-REPLAY.md`).
- 2026-10-20 — **verifica integrità**: ricalcolati gli SHA-256 dei 25 file protetti
  (`Modelli/` + `Progetto/Articolo Blog/`): **0 mancanti, 0 diversi** dopo tutta la pulizia.
- 2026-10-20 — **runtime sfoltito** (`tools/trim_runtime.py`): spostati in
  `da_eliminare/runtime-package-trim/` 556,6 MB di pacchetti non usati dall'app
  (gradio 56,6 MB, tensorboard + plugin 11,5 MB, onnx 23,8 MB, onnxruntime 419,2 MB,
  onnxconverter/skl2onnx 1,3 MB, torch-directml + onnxruntime-dml 44,2 MB).
  Verifica post-trim: import di torch/rvc_python/fastapi/soundfile OK, `--doctor` OK,
  conversione reale CUDA OK (RTF 0,32).

Stato finale: `runtime/` ≈5,65 GB; `da_eliminare/` contiene tutto il resto, con
`INVENTARIO.md` e `quarantine-manifest.json` per il ripristino.
