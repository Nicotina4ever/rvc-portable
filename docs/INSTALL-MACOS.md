# Installazione — macOS 12+ (Apple Silicon / Intel)

## Requisiti

| Voce | Note |
|---|---|
| macOS | 12 Monterey o superiore (consigliato 13+) |
| Python | **3.10+** (python.org o Homebrew) |
| Xcode Command Line Tools | necessari per compilare `fairseq` (`xcode-select --install`) |
| Disco | ~7 GB liberi (runtime venv + spazio lavoro) |
| Modelli `.pth` | a parte, in `Modelli/` |

`ffmpeg` **non serve**: la decodifica usa PyAV incluso nelle dipendenze.

## Installazione

Scegli una cartella scrivibile, ad esempio `~/Applications/RVC-Portable`:

```bash
git clone https://github.com/Nicotina4ever/rvc-portable.git ~/Applications/RVC-Portable
cd ~/Applications/RVC-Portable
chmod +x setup.sh run.sh run.command
./setup.sh
```

`setup.sh` chiama `tools/bootstrap.py --install`:

1. crea `runtime/` come virtualenv Python 3.10;
2. installa `pip<24.1` (richiesto da `omegaconf==2.0.6`);
3. installa `requirements/base.txt` e `requirements/engine-posix.txt`
   (`torch==2.2.2`, `numpy==1.23.5`, `faiss-cpu==1.7.3`, `rvc-python==0.1.5`, `fairseq==0.12.2`…);
4. verifica import e motore.

Opzioni:

```bash
./setup.sh --profile cpu      # forza CPU (torch CPU)
./setup.sh --profile mps      # Apple Silicon (sperimentale per RVC)
./setup.sh --profile cuda118  # eGPU NVIDIA (raro su Mac)
./setup.sh --offline wheelhouse/   # installazione offline da wheel locali
```

## Avvio

```bash
./run.command      # doppio click nel Finder oppure da terminale
./run.sh           # equivalente da terminale
```

- Si apre una finestra app dedicata se Chrome/Chromium/Edge è installato, altrimenti il
  browser predefinito.
- Modalità server: `./run.sh --headless --console` (stampa l'URL con il token).

## Configurazione iniziale

Per il flusso telefono **Android** ↔ Dropbox ↔ PC: tab **Cloud** → **Rileva Dropbox** → **Attiva preset**.

Per l'uso locale:

1. Tab **Configurazione**: cartella input, output, modello `.pth` e indice.
2. **Salva** → tab **Monitor** → **Avvia monitoraggio**.
3. Metti un file audio nella cartella input.

MPS è **sperimentale** con RVC: se la conversione fallisce o è instabile, imposta device `cpu`
nelle Avanzate (più lento ma affidabile).

## Verifica

```bash
./runtime/bin/python3 -m app --doctor
```

Esito atteso `OK`. In caso di problemi: `data/logs/` e [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Aggiornare

```bash
cd ~/Applications/RVC-Portable
git pull
./setup.sh        # solo se i requisiti sono cambiati
```

## Disinstallare

Elimina la cartella di installazione (conserva prima `Modelli/` e `data/config.json`).
Se hai usato la modalità non portatile: `~/Library/Application Support/NLTools/RVC`.

## Problemi comuni

- **`fairseq` non compila** → mancano i Command Line Tools: `xcode-select --install`.
- **Python 3.10 non trovato** → installa da python.org o `brew install python@3.10`.
- **La finestra non si apre** → guarda `data/logs/stdout.log`; prova `./run.sh --console`.
- **Gatekeeper** → al primo avvio potrebbe chiedere conferma: *Apri comunque*.
