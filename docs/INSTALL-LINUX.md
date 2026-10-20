# Installazione — Linux (x86_64)

## Requisiti (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-dev \
                    build-essential libsndfile1 pkg-config git
```

Per CUDA: driver NVIDIA proprietari installati (CUDA 11.8 compatibile) e `nvidia-smi` funzionante.

## Installazione

Scegli una cartella scrivibile, ad esempio `~/opt/rvc-portable`:

```bash
git clone https://github.com/Nicotina4ever/rvc-portable.git ~/opt/rvc-portable
cd ~/opt/rvc-portable
chmod +x setup.sh run.sh
./setup.sh --profile cuda118    # oppure --profile cpu
```

Il bootstrap crea `runtime/` (venv Python 3.10), installa `pip<24.1` (per `omegaconf==2.0.6`),
`requirements/base.txt` e `requirements/engine-posix.txt`, verifica il motore.

Opzioni:

```bash
./setup.sh --profile cpu           # nessuna GPU
./setup.sh --profile cuda118       # NVIDIA
./setup.sh --offline wheelhouse/   # installazione da wheel locali
```

## Avvio

```bash
./run.sh
```

- Se Chrome/Chromium/Edge è presente si apre una finestra app dedicata; altrimenti il browser
  predefinito.
- Modalità server (no browser): `./run.sh --headless --console` — stampa l'URL con il token.

## Configurazione iniziale

Per il flusso telefono **Android** ↔ Dropbox ↔ PC: tab **Cloud** → **Rileva Dropbox** → **Attiva preset**.

Per l'uso locale:

1. Tab **Configurazione**: cartella input, output, modello `.pth` e indice.
2. **Salva** → tab **Monitor** → **Avvia monitoraggio**.
3. Metti un file audio nella cartella input.

## Verifica

```bash
./runtime/bin/python3 -m app --doctor
./run.sh --headless --console &
# poi: curl http://127.0.0.1:<porta>/api/health
```

## Aggiornare

```bash
cd ~/opt/rvc-portable
git pull
./setup.sh        # solo se i requisiti sono cambiati
```

## Disinstallare

Elimina la cartella di installazione (conserva prima `Modelli/` e `data/config.json`).
Se hai usato la modalità non portatile: `~/.local/share/NLTools/RVC`.

## Problemi comuni

- **`fairseq` non compila** → installa `build-essential` e `python3.10-dev`.
- **`libsndfile` mancante** → `sudo apt install libsndfile1`.
- **CUDA non rilevata** → controlla `nvidia-smi` e i driver; usa `--profile cpu` nel frattempo.
- **Manca un browser** → `./run.sh --browser none` e apri l'URL stampato.
- **Wayland/PipeWire** → se la finestra app non parte, usa il browser predefinito
  (`--browser default`).
