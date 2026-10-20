# Confronto architetture e prima/dopo (v2 → v3)

Documento di supporto alla decisione architetturale della versione 3.0
(il riferimento `table.md` della richiesta).

## 1. Opzioni valutate

| Criterio | GUI CustomTkinter (v2) | **Web SPA + FastAPI (scelta)** | Electron/Tauri + React | pywebview + FastAPI |
|---|---|---|---|---|
| Peso distribuzione extra | ~0 | **~0** | +80–150 MB | +5–15 MB |
| Dipendenze runtime | tkinter | **browser di sistema** | Node/Chromium | WebView2/WKWebView/GTK |
| Avvio percepito | 1–2 s + torch nel processo UI | **1–2 s backend + ~1 s UI** | 2–4 s | 1–2 s |
| Aspetto/UX | limitato | **alto, personalizzabile** | alto | alto |
| Multi-OS | sì (Tk) | **sì** | sì | dipende dai webview |
| Testabilità | scarsa | **API + E2E** | media | media |
| Build toolchain | nessuna | **nessuna** | Node/Rust | nessuna |
| Accesso remoto opt-in | no | **sì** | no | possibile |
| Aggiornamento UI | riavvio | **refresh** | rebuild | refresh |
| Manutenzione | 1 file monolitico | **moduli separati** | complessa | media |

**Decisione**: SPA statica + FastAPI. Massimo rapporto valore/rischio: nessun runtime aggiuntivo,
stessa UX su tre OS, API testabile, UI evolvibile senza toccare il motore.

## 2. Motore: opzioni valutate

| Opzione | Python | torch | fairseq | Stato | Note |
|---|---|---|---|---|---|
| rvc-python 0.1.5 sul runtime 3.12 | 3.12 | 2.7.1 | 0.12.2 | **impossibile** | pin `numpy<=1.23.5`/`faiss==1.7.3` senza wheel cp312; fairseq solo sdist; torch ≥ 2.6 rompe `torch.load` |
| **rvc-python 0.1.5 + Python 3.9 (runtime storico)** | **3.9.13** | **2.0.0+cu118** | **0.12.2** | **verificato** | conversione reale CUDA, offline, pesi inclusi |
| rvc-python + Python 3.10 (ricetta macOS) | 3.10 | 2.1/2.2 | 0.12.2 | verificato su macOS | usato per POSIX; fairseq da compilare |
| Fork fairseq py3.12 | 3.12 | 2.7 | fork | non verificato | fork piccoli, fermo 2023, `weights_only` resta un blocco |
| Applio (senza fairseq) | 3.10–3.13 | 2.11 | no | verificato come app | richiederebbe di sostituire l'engine e verificare la qualità |
| uziproj/rvc "Simple RVC" | 3.10–3.12 | ≥2.3 | no | probabile | progetto giovane; da valutare come evoluzione |
| ONNX inference | 3.10–3.12 | irrilevante | no | probabile | richiede modelli convertiti |

**Decisione**: ripristinare il runtime 3.9 verificato per Windows; Python 3.10 per macOS/Linux;
documentare il percorso moderno (Applio/uziproj/ONNX) come evoluzione futura.

## 3. Prima / dopo

| Aspetto | v2 (prima) | v3 (dopo) |
|---|---|---|
| Avvio Windows | `run.bat` → `pythonw app.py` (GUI Tk) | `run.bat` → `launch.py` → backend + finestra app |
| Motore | **assente**: `python -m rvc_python` falliva | worker persistente, modello caldo, conversione verificata |
| Errori all'avvio | invisibili (pythonw senza log) | log + dialog nativo + `fatal.log` |
| UI | 1 file, 626 righe, 4 tab | SPA modulare, 7 viste, tema chiaro/scuro, responsive |
| Lingua | cambio con riavvio, stringhe miste | IT/EN istantaneo, catalogo unico |
| Coda | thread che si accavallano, spin-wait | coda FIFO, 1 worker GPU, cancel/retry/dedupe |
| Config | piatto, scritture non atomiche | schema v3, atomico, backup, migrazione, hot-reload non distruttivo |
| Cloud | SDK Dropbox + App Key fissa (errore `invalid_client`) | client PKCE proprio, App Key configurabile, errori azionabili |
| Indice `trained_*` | ignorato in silenzio | alias `added_*` automatico |
| Diagnostica | assente | `--doctor` + pannello Avanzate |
| Test | nessuno | unit + integrazione + e2e; CI 3 OS |
| Multi-OS | `run.sh` + wizard Windows-only | bootstrap macOS/Linux + launcher dedicati + CI |
| Riordino | 5,4 GB di vecchie distribuzioni al root, 7,6 GB runtime inutilizzabile | `da_eliminare/` con inventario; root ~20 voci |
| Documentazione | readme 2025 + walkthrough | README, architettura, install per OS, cloud, troubleshooting, migrazione |

## 4. Riordino in sintesi

| Area | Prima | Dopo |
|---|---|---|
| Runtime | 7,66 GB Python 3.12 **senza motore** | 5,65 GB Python 3.9 **funzionante** (`runtime/`), vecchio in quarantena |
| Vecchie distribuzioni | 5,47 GB in `Progetto/` | in `da_eliminare/distribuzioni-precedenti/` |
| Codice v2 | 7 moduli al root + `lang/` | in `da_eliminare/versione-2.0/` |
| Requirements | 3 file obsoleti | `requirements/{base,engine-windows,engine-posix,dev}.txt` |
| Modelli | `Modelli/` + modello in `Progetto/...` | `Modelli/` intatta; modello Paolo in `Modelli/Archivio/Paolo/` |
| Blog | `Progetto/Articolo Blog/` | **intatta** |
| Cache | `__pycache__` sparsi | rimossi |

Dettaglio completo: [../da_eliminare/INVENTARIO.md](../da_eliminare/INVENTARIO.md) e
[CLEANUP-LOG.md](CLEANUP-LOG.md).

## 5. Costi e limiti accettati

- Python 3.9 EOL sul runtime Windows: bloccato da fairseq/torch; documentato e isolato.
- fairseq da compilare su macOS/Linux: richiede Xcode CLT/build-essential; il bootstrap lo spiega.
- MPS sperimentale; DirectML non supportato.
- Modello singolo in VRAM: niente conversione parallela (scelta esplicita per 8 GB di VRAM).
- La UI non fa parte di un processo nativo: richiede un browser installato (su Windows Edge c'è
  sempre; su macOS/Linux è documentato il fallback).
