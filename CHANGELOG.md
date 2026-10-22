# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) · Versione semantica.

## [3.0.0] — 2026-10-20

Riscrittura completa: architettura frontend/backend, ripristino del motore RVC, multi-OS e riordino.

### Corretto

- **Motore RVC assente**: il runtime Python 3.12 non conteneva `rvc_python`/`fairseq` e ogni
  conversione falliva (la CLI `-m rvc_python` usciva con errore). Il runtime 3.12 è stato
  sostituito con il runtime portatile verificato **Python 3.9.13 + torch 2.0.0+cu118 +
  rvc-python 0.1.5 + fairseq 0.12.2**, con pesi HuBERT/RMVPE inclusi (nessuna rete richiesta).
- **Finestra CMD all'avvio**: `run.bat` lancia `pythonw` e non mostra console; in caso di errore
  ora scrive su `data/logs` e mostra un dialog nativo (prima gli errori erano invisibili).
- **Dropbox `Invalid client_id`**: la App Key non è più fissa; è configurabile nella tab Cloud e
  gli errori OAuth vengono tradotti con istruzioni (creare Scoped App, incollare la chiave).
- **Indice `trained_*` ignorato**: risolto con alias automatico `added_*` nella cache.
- **DirectML/fcpe**: rimossi dalla UI perché non supportati dal motore (prima fallivano in silenzio).
- **Deadlock all'avvio del worker** (Windows): il caricamento della DLL OpenBLAS di numpy andava
  in stallo se un thread era già in attesa su stdin; ora il worker fa warm-up di torch/rvc-python
  prima di avviare il lettore dei comandi (pronto in ~4,5 s, poi `load` in ~0,3 s).
- **Riavvio con job appesi**: i job rimasti `queued`/`running` su disco vengono marcati
  `failed/interrupted` all'avvio, senza restare per sempre "in coda".
- **Monitoraggio all'avvio**: `monitor.enabled_on_start` ora viene rispettato davvero (prima era
  solo un'impostazione salvata): aprendo l'app il watcher parte da solo sulla cartella configurata.
- **Riconversione stesso nome**: la chiave di deduplica include ora dimensione e mtime del file,
  quindi un file ricaricato con lo stesso nome (tipico del flusso telefono) viene rielaborato.
- **Dropbox in sincronizzazione continua**: `config.json` non viene più riscritto dal PC a ogni
  salvataggio (era il loop principale): è un flusso telefono → PC, applicato in hot-reload senza
  rimbalzo. Anche le normali modifiche impostazioni del PC non toccano più Dropbox. `status.json`
  viene aggiornato solo quando cambia lo stato, con heartbeat ogni 5 minuti
  (`android.status_heartbeat_s`). Dopo una config Android lo stato viene aggiornato subito.

### Aggiunto

- **Ponte Android/Dropbox** (flusso principale del progetto): l'app mini-DAW Android registra e
  monta, carica il WAV in `Dropbox/TestRVC/AudioIn` e attende `AudioOut/<stesso nome>.wav`.
  Il PC, con il solo **client Dropbox desktop**, monitora la cartella, applica il `config.json`
  scritto dal telefono (hot-reload), converte e riscrive il risultato: nessun token sul PC.
  Preset con auto-rilevamento Dropbox, `modelli.txt` generato dai modelli del PC, config ibrida
  v3+piatto, output con lo stesso nome, monitor auto-avviato. Dettagli: `docs/ANDROID-BRIDGE.md`.
- **Controllo remoto PC dall'Android**: il PC scrive `status.json` nella cartella condivisa (heartbeat ogni ~5 s con motore, device, coda, watcher, ultima config applicata e parametri audio). L'app mostra ONLINE/OFFLINE e permette di inviare `config.json` con pitch/formant/index rate/protezione/metodo/modello: il PC applica con hot-reload in ~2 s. Nessuna porta aperta, nessuna VPN.
- **Cartelle modelli extra** (`audio.extra_model_dirs`): i modelli possono stare in `Modelli/`, in
  una cartella Dropbox o altrove; scansione, `modelli.txt` e UI li includono.
- **ConfigSync** (`app/android_bridge.py`): hot-reload reale di `cloud.local_path` (config v3 o
  piatto Android), con riscrittura ibrida per tener allineati PC e telefono.
- Backend **FastAPI** locale con token, controllo Host/Origin, CSP e nessun CORS.
- Interfaccia **SPA zero-build** (HTML/CSS/JS) con temi chiaro/scuro, IT/EN istantaneo,
  dashboard, configurazione, monitor, modelli, cloud e avanzate.
- **Coda job** con worker GPU singolo, modello caldo in cache, progresso, cancel, retry,
  deduplica e cronologia persistente.
- **SSE** (`/api/events`) per log, job, monitor, configurazione e motore.
- **Diagnostica** (`--doctor`, `/api/system/diagnostics`) con controlli e suggerimenti.
- **Config schema v3** annidato, scrittura atomica, backup `.bak`, migrazione automatica dal v2.
- **Dropbox client proprio** (PKCE, refresh token, conflitti, retry) senza SDK.
- **Launcher multi-OS**: `run.bat`, `run-console.bat`, `run.sh`, `run.command`, `setup.bat`, `setup.sh`.
- **Quarantena** `da_eliminare/` con inventario e ripristino (`tools/quarantine.py`).
- **Distribuzione GitHub**: repository solo sorgenti (~3 MB) e installer `setup.bat` che scarica
  una sola volta il runtime del motore (~3,5 GB) da un asset della Release, verifica SHA-256 e
  gestisce la divisione in parti oltre il limite GitHub di 2 GiB. Config in `install.conf`,
  build dell'asset con `tools/build_runtime_asset.py`, controllo igiene con `tools/check_repo.py`.
  Guide: `docs/INSTALL.md` (utenti) e `docs/PUBLISHING.md` (maintainer).
- **Runtime sfoltito**: `tools/trim_runtime.py` sposta in quarantena i pacchetti non usati
  (gradio, tensorboard, onnx/onnxruntime, DirectML): **−556,6 MB** sul runtime.
- **Screenshot UI** in `docs/img/` (dashboard, configurazione, monitor, modelli, cloud, avanzate),
  catturabili con `tools/screenshots.py`.
- **E2E reali**: `tests/e2e/run_real_conversion.py` (motore), `tests/e2e/run_api_e2e.py`
  (API, audio, Range, waveform, shutdown) e `tests/e2e/run_android_bridge.py` (telefono →
  AudioIn → PC → AudioOut, con FakeEngine).
- Documentazione: architettura, installazione per OS, cloud, troubleshooting, migrazione,
  contratto API, confronto con la 2.0.
- Test unitari/integrazione (193 test) e CI GitHub Actions su Windows/macOS/Linux, release tool.

### Cambiato

- Avvio senza console: la variante di debug è `run-console.bat`.
- Dati utente spostati in `data/` (portatile) con fallback alla cartella utente.
- `config.json` migrato in `data/config.json` (schema v3).
- Catalogo traduzioni unico in `locales/` (IT/EN) servito anche al backend.
- Runtime del motore gestito da `tools/bootstrap.py` (check/install/offline/restore).

### Rimosso / archiviato

- GUI CustomTkinter, script sparsi della 2.0, vecchi requirements, vecchie distribuzioni
  (Windows/macOS/Linux) e backup: spostati in `da_eliminare/` (nessuna cancellazione).
- Dipendenze inutilizzate: `customtkinter`, `dropbox` SDK, `gradio` residuo.

### Note

- PyTorch deve restare `< 2.6` (fairseq + `torch.load`).
- macOS/Linux richiedono Python 3.10 e la compilazione di fairseq (Xcode CLT / build-essential).
- Il modello `LoZio` della vecchia distribuzione è stato conservato in `Modelli/Archivio/Paolo/`.
