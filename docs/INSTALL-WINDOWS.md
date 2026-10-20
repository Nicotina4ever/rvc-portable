# Installazione — Windows 10/11 (x64)

## Requisiti

| Voce | Minimo | Consigliato |
|---|---|---|
| Sistema | Windows 10 64 bit | Windows 11 |
| RAM | 8 GB | 16 GB |
| Disco | 12 GB liberi (installazione) | 16 GB |
| GPU | — (CPU funziona) | NVIDIA con driver CUDA 11.8+ (≥ 520) |
| Browser | Edge (preinstallato) | Edge o Chrome aggiornati |
| Python | **non richiesto** | — |

Il **runtime Python 3.9.13 con il motore RVC** (PyTorch, fairseq, rvc-python, pesi HuBERT/RMVPE)
non è versionato nel repository: lo scarica `setup.bat` al primo avvio (~3,5 GB, una volta sola).
Chi preferisce può usare un archivio già scaricato (vedi *Installazione offline*).

## Installazione in 3 passi

Scegli una cartella **scrivibile** (es. `D:\App\RVC-Portable`); evita `C:\Program Files`,
perché l'app scrive `data/` accanto a sé e non richiede permessi di amministratore.

1. **Scarica il progetto** in quella cartella:
   - con git: `git clone https://github.com/Nicotina4ever/rvc-portable.git "D:\App\RVC-Portable"`
   - oppure scarica lo ZIP dalla pagina GitHub (Code → Download ZIP) e scompattalo lì.
2. **Doppio click su `setup.bat`**: scarica il runtime, verifica l'hash SHA-256, lo estrae e
   controlla l'ambiente. La prima volta richiede qualche minuto; le volte successive è istantaneo.
3. **Doppio click su `run.bat`**: parte l'app, senza finestra CMD.

Da terminale:

```bat
cd /d "D:\App\RVC-Portable"
setup.bat
run.bat
```

### Configurazione iniziale nell'app

Per il flusso telefono **Android** ↔ Dropbox ↔ PC: tab **Cloud** → **Rileva Dropbox** → **Attiva preset** (crea AudioIn/AudioOut, modelli.txt e config condiviso).

Per l'uso locale:

1. Tab **Configurazione**: imposta cartella input, output, modello `.pth` e indice `.index`.
2. Premi **Salva**.
3. Tab **Monitor**: **Avvia monitoraggio**.
4. Metti un file audio nella cartella input (o trascinalo nella Dashboard).

I modelli vanno in `Modelli/` (puoi anche puntare a un'altra cartella dalla UI).

## Installazione offline o con archivio locale

Se hai già l'archivio del runtime (es. `RVC-Portable-runtime-windows-py39-cu118.zip`):

```bat
set "RVC_RUNTIME_ZIP=D:\Download\RVC-Portable-runtime-windows-py39-cu118.zip"
setup.bat
```

`setup.bat` riconosce anche `RVC_RUNTIME_URL` e `RVC_RUNTIME_SHA256` come override di
`install.conf` (utili per mirror aziendali o download bloccati dalla rete).

## Verifica

```bat
runtime\python.exe -m app --doctor
```

Esito atteso: `OK` per *Interprete del motore*, *PyTorch* (< 2.6), *Motore rvc-python*,
*Fairseq*, *Pesi base*, *Percorsi*, *Interfaccia web*; *CUDA* se hai una GPU NVIDIA.

## Aggiornare

```bat
cd /d "D:\App\RVC-Portable"
git pull
```

Se `setup.bat` segnala un runtime obsoleto, rilancialo: scarica la versione aggiornata
mantenendo `data/` e `Modelli/`.

## Debug

| Comando | Uso |
|---|---|
| `run.bat` | avvio normale senza console |
| `run-console.bat` | avvio con log a video (debug) |
| `runtime\python.exe -m app --doctor --doctor-json` | diagnostica in JSON |
| `runtime\python.exe -m app --headless --console` | solo server, stampa l'URL |
| `tools\bootstrap.py --check` | verifica rapida dell'ambiente |

Log: `data\logs\app.log`, `engine.log`, `stdout.log`, `fatal.log`.

## Sviluppo (checkout senza runtime)

Il repository non versiona `runtime/` né `Modelli/`. Sul tuo Windows di sviluppo:

```bat
:: 1) costruisci/scarica il runtime una volta
runtime\python.exe -B tools\build_runtime_asset.py --skip-check --update-install-conf
::    oppure ripristina un archivio storico:
runtime\python.exe -B tools\bootstrap.py --restore "Progetto\RVC-PortableConMonitoraggio.zip"

:: 2) strumenti di sviluppo
runtime\python.exe -B tools\bootstrap.py --dev

:: 3) test
runtime\python.exe -B tools\dev.py test
runtime\python.exe -B tools\dev.py lint
```

## Disinstallazione

1. Chiudi l'app (finestra o pulsante Esci).
2. Elimina la cartella di installazione.
3. Se hai usato la modalità non portatile: elimina anche `%LOCALAPPDATA%\NLTools\RVC`.

I modelli in `Modelli/` sono tuoi: spostali prima di eliminare la cartella.

## Problemi comuni

Vedi [TROUBLESHOOTING.md](TROUBLESHOOTING.md). In sintesi:

- **`setup.bat` si chiude subito** → esegui da Esplora file (doppio click) e leggi il messaggio;
  controlla la connessione e che `install.conf` abbia URL e hash validi.
- **"hash SHA-256 non corrispondente"** → archivio corrotto o `install.conf` di una versione
  precedente: riscarica l'asset dalla Release o chiedi al maintainer l'hash aggiornato.
- **Nessuna finestra si apre** → guarda `data\logs\stdout.log` e `fatal.log`; prova `run-console.bat`.
- **"Motore non disponibile"** → runtime incompleto: `runtime\python.exe -B tools\bootstrap.py --check`.
- **CUDA non rilevata** → aggiorna i driver NVIDIA; l'app funziona comunque su CPU.
- **SmartScreen/antivirus** → l'app non è firmata: consenti l'esecuzione della cartella.
