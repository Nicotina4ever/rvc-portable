# Risoluzione problemi

Prima di tutto: **`python -m app --doctor`** (o `runtime\python.exe -m app --doctor` su Windows).
Ogni check ha un `id`, un messaggio e un suggerimento (`fix`). I log sono in `data/logs/`.

## Installazione da GitHub
| Sintomo | Causa | Rimedio |
|---|---|---|
| `setup.bat` si chiude subito | messaggio non letto o rete assente | eseguilo da Esplora file (doppio click) e leggi il testo; verifica la connessione |
| Download interrotto / lento | rete instabile o proxy | riprova; oppure scarica l'asset dalla pagina **Releases** e usa `set "RVC_RUNTIME_ZIP=percorso.zip"` |
| "hash SHA-256 non corrispondente" | archivio corrotto o `install.conf` di un'altra versione | riscarica l'asset dalla Release; il maintainer aggiorna l'hash con `tools/build_runtime_asset.py --update-install-conf` |
| "estrazione incompleta: manca runtime\python.exe" | spazio disco insufficiente o archivio parziale | libera ~9 GB, riscarica e riprova |
| `run.bat` dice "Runtime non installato" | `setup.bat` non eseguito | esegui `setup.bat` una volta nella cartella del progetto |
| `setup.sh` non trova Python 3.10 | interpreti mancanti | macOS: python.org/Homebrew; Linux: `sudo apt install python3.10 python3.10-venv` |
| `fairseq` non compila (macOS/Linux) | toolchain assente | macOS: `xcode-select --install`; Linux: `build-essential python3.10-dev` |
| GitHub non accetta il push | file troppo grande versionato | `python tools/check_repo.py`: rimuovi il file e aggiungi la regola al `.gitignore` |
| Release: upload asset fallito (2 GiB) | limite GitHub per singolo asset | lo zip del runtime viene diviso in parti `.001`, `.002`... da `build_runtime_asset.py` |

## Ponte Android / Dropbox

| Sintomo | Causa | Rimedio |
|---|---|---|
| Il telefono resta in attesa e non arriva nulla in `AudioOut` | Dropbox desktop non sincronizza o monitor spento | verifica che `J:\...\Dropbox\TestRVC\AudioIn` locale riceva il file; Dashboard → Avvia monitoraggio; riattiva il preset (imposta l'avvio automatico) |
| Il file compare in `AudioIn` ma non viene convertito | estensione non supportata o file ancora in scrittura | usa `.wav/.mp3/.ogg/.m4a/.flac/.aac/.opus/.wma`; il watcher attende ~1,5 s di stabilità |
| `config.json` del telefono ignorato | hot-reload spento o percorso sbagliato | Cloud → "Percorso locale o NAS" = `…\TestRVC\config.json`, hot reload attivo; premi **Applica config** |
| `modelli.txt` vecchio/senza modelli | modelli aggiunti dopo il preset | Cloud → **Sincronizza modelli**; oppure riavvia il preset |
| Il telefono mostra un modello ma il PC non lo trova | `modelli.txt` generato su un altro PC | rigenera `modelli.txt` da questo PC (i percorsi sono locali) |
| Output in `AudioOut` con nome diverso | preset non attivo (`same_name_output`) | Cloud → **Attiva preset** di nuovo; verifica `android.enabled` nel doctor |
| Errori su nomi file | caratteri non validi (`? : *`) | rinomina il file/clip con lettere, numeri, `-`, `_` |

Dettagli completi: [ANDROID-BRIDGE.md](ANDROID-BRIDGE.md).

## Avvio

| Sintomo | Diagnosi | Rimedio |
|---|---|---|
| Nessuna finestra, nessun errore | log non visibile (pythonw) | `run-console.bat` / `./run.sh --console`; leggi `data/logs/stdout.log` e `fatal.log` |
| "Un'istanza è già attiva" (non si apre nulla) | processo zombie o istanza precedente | chiudi il processo `pythonw`/`python` residuo; cancella `data/state/instance.json` |
| Porta occupata | conflitto rete | l'app sceglie una porta libera; se usi `--port`, scegline un'altra |
| Antivirus blocca l'exe | non firmato | aggiungi la cartella alle esclusioni |
| SmartScreen su `run.bat` | file scaricato | *Ulteriori informazioni → Esegui comunque* |
| Crash immediato | dipendenza mancante | `data/logs/fatal.log` + `tools/bootstrap.py --check` |

## Motore

| Check | Sintomo | Causa | Rimedio |
|---|---|---|---|
| `engine` | "Motore non disponibile" | `rvc_python` assente | esegui `setup.bat` (Windows) o `./setup.sh` (macOS/Linux); con archivio locale `set "RVC_RUNTIME_ZIP=..."` |
| `fairseq` | idem | `fairseq` assente/incompatibile | usa il runtime 3.9 incluso; su macOS/Linux ricompila con Xcode CLT/build-essential |
| `torch` | `torch >= 2.6` | runtime aggiornato per errore | ripristina i pin (`torch==2.0.0+cu118` Windows, `2.2.2` POSIX): da 2.6 fairseq non carica i checkpoint |
| `base_models` | pesi mancanti/troncati | download interrotto o cartella spostata | ripristina `runtime/.../rvc_python/base_model/{hubert_base.pt,rmvpe.pt}` |
| `cuda` | `False` | driver assenti/vecchi | aggiorna i driver NVIDIA; l'app funziona su CPU |
| — | "CUDA out of memory" | VRAM insufficiente | chiudi altri programmi GPU; un solo job alla volta; usa un modello più piccolo |

## Conversione

| Sintomo | Causa | Rimedio |
|---|---|---|
| Output silenzioso | audio di input troppo corto/senza voce, oppure errore motore | controlla `data/logs/engine.log`; usa un file vocale > 1 s |
| Qualità bassa / voce "metallica" | indice non applicato | l'app risolve automaticamente `trained_*` → `added_*`, ma verifica che il file `.index` esista e corrisponda al `.pth` |
| Errore indice | mismatch modello/indice | seleziona l'indice corretto nella tab Modelli |
| Conversione lentissima | device `cpu` | tab Avanzate → device `auto`/`cuda:0` |
| MPS error (macOS) | op non supportate | device `cpu` |
| DirectML non elencato | non supportato da rvc-python | usa CUDA o CPU |
| Metodo `fcpe` assente | rvc-python 0.1.5 non lo accetta | usa `rmvpe`, `harvest`, `crepe`, `pm` |

## Monitoraggio

| Sintomo | Causa | Rimedio |
|---|---|---|
| Il file non viene rilevato | cartella di rete lenta | usa modalità `polling` (Avanzate) o attendi la stabilizzazione (1,5 s) |
| File riprocessato al riavvio | dedupe azzerata | il dedupe è in `data/state/processed.json`; rimuovi la voce solo se vuoi riprocessare |
| Doppia conversione | file copiato in due passaggi | il watcher attende size+mtime stabili e deduplica |

## Cloud

| Sintomo | Causa | Rimedio |
|---|---|---|
| `Invalid client_id` | App Key non registrata | crea una Scoped App e incolla la App Key ([CLOUD-SYNC.md](CLOUD-SYNC.md)) |
| `invalid_grant` | codice scaduto | riavvia *Connetti* |
| Conflitto upload | remoto modificato | conferma "forza" o scarica prima |
| Hot-reload non scatta | file su unità di rete lenta | polling 3 s; verifica che il percorso sia il file (non la cartella) |

## Frontend

| Sintomo | Causa | Rimedio |
|---|---|---|
| Pagina bianca | asset mancanti | `web/index.html` presente? reinstalla l'app |
| "401 unauthorized" | token assente/scaduto | riapri dal launcher (genera un nuovo token) |
| Finestra app non si apre | Edge/Chrome assenti | usa `--no-app-mode` o il browser predefinito |
| Layout rotto | cache del browser | Ctrl+F5 |

## Raccolta informazioni per una segnalazione

1. `python -m app --doctor-json > diagnostica.json`
2. copia `data/logs/` (app.log, engine.log, fatal.log)
3. versione OS, GPU, driver, versione app (footer).
