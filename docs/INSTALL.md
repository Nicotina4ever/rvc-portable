# Installazione — tutte le piattaforme

RVC Portable si installa **da solo** in una cartella a tua scelta: il repository GitHub
resta leggero (~3 MB di sorgenti), mentre al primo avvio `setup.bat` (Windows) scarica
una volta il **runtime del motore** (~3,5 GB, con Python 3.9.13 + PyTorch + RVC già pronti).
Nessun installer amministrativo, nessuna cartella di sistema: tutto vive nella cartella che scegli.

- **Windows** (verificato): [INSTALL-WINDOWS.md](INSTALL-WINDOWS.md)
- **macOS** (Apple Silicon / Intel): [INSTALL-MACOS.md](INSTALL-MACOS.md)
- **Linux** (x86_64): [INSTALL-LINUX.md](INSTALL-LINUX.md)

## Requisiti minimi

| | Windows | macOS | Linux |
|---|---|---|---|
| Sistema | Windows 10/11 64 bit | macOS 12+ | distro 64 bit aggiornata |
| Python | **non richiesto** (runtime scaricato da `setup.bat`) | 3.10+ | 3.10+ |
| Strumenti | — | Xcode Command Line Tools | `build-essential`, `python3-dev`, `libsndfile1` |
| Disco | ~12 GB liberi durante l'installazione (~7 GB dopo) | ~7 GB | ~7 GB |
| GPU | opzionale; NVIDIA CUDA 11.8+ consigliata | opzionale; MPS sperimentale | opzionale; NVIDIA CUDA 11.8+ |
| Browser | Edge o Chrome | Safari/Chrome/Edge | Chrome/Chromium |

La conversione funziona **anche su CPU** (più lenta); la GPU è consigliata.

## Scegliere la cartella di installazione

L'app è portatile: la cartella in cui metti i file **è** la cartella di installazione.
Scegline una scrivibile dall'utente, per esempio:

- Windows: `D:\App\RVC-Portable` (evita `C:\Program Files`)
- macOS: `~/Applications/RVC-Portable`
- Linux: `~/opt/rvc-portable`

Al primo avvio l'app crea al suo interno `data/` (config, log, stato). I modelli vocali
vanno in `Modelli/`. Non serve alcun permesso di amministratore.

## Windows: installazione in 3 passi

1. **Scarica il progetto**: `git clone https://github.com/Nicotina4ever/rvc-portable.git "D:\App\RVC-Portable"`
   oppure scarica lo ZIP dalla pagina GitHub e scompattalo nella cartella scelta.
2. **Doppio click su `setup.bat`**: scarica il runtime, verifica l'hash SHA-256, lo estrae e
   controlla l'ambiente (la prima volta richiede qualche minuto).
3. **Doppio click su `run.bat`**: si apre la finestra dell'app, senza console.
4. Al primo avvio: **Cloud → Rileva Dropbox → Attiva preset** per il flusso telefono ↔ Dropbox ↔ PC (vedi [ANDROID-BRIDGE.md](ANDROID-BRIDGE.md)).

In alternativa, da terminale:

```bat
cd /d "D:\App\RVC-Portable"
setup.bat
run.bat
```

Se hai già l'archivio del runtime (es. per uso offline):

```bat
set "RVC_RUNTIME_ZIP=D:\Download\RVC-Portable-runtime-windows-py39-cu118.zip"
setup.bat
```

## macOS e Linux

```bash
git clone https://github.com/Nicotina4ever/rvc-portable.git
cd rvc-portable
chmod +x setup.sh run.sh run.command

./setup.sh                  # crea runtime/ (venv Python 3.10) e installa il motore
./run.command               # macOS: doppio click oppure da terminale
./run.sh                    # Linux
```

Opzioni utili:

```bash
./setup.sh --profile cpu       # forza CPU (nessuna GPU)
./setup.sh --profile cuda118   # Linux con NVIDIA CUDA 11.8
./setup.sh --offline wheelhouse/   # installazione da wheel locali
```

## Aggiornare

```bash
cd /percorso/rvc-portable
git pull
```

Se sono cambiati i requisiti, rilancia `setup.bat` / `./setup.sh`: il runtime viene
riutilizzato se già presente. I tuoi dati in `data/` e i modelli in `Modelli/` non vengono toccati.

## Disinstallare

1. Chiudi l'app.
2. Elimina la cartella di installazione (opzionale: conserva `Modelli/` e `data/config.json`).

## Verifica e problemi

```bat
runtime\python.exe -m app --doctor
```

```bash
./runtime/bin/python3 -m app --doctor
```

Diagnostica completa: `data/logs/` e [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
