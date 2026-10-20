# Requirements

Pin divisi per profilo, ricavati dal runtime verificato (non da "ultima versione").

| File | Quando usarlo |
|---|---|
| `base.txt` | dipendenze comuni backend/UI/audio (FastAPI, watchdog, soundfile, PyAV…) |
| `engine-windows.txt` | motore su Windows: Python 3.9.13 + torch 2.0.0+cu118 + rvc-python 0.1.5 + fairseq 0.12.2 |
| `engine-posix.txt` | motore su macOS/Linux: Python 3.10 + torch 2.2.2 + stessi pin applicativi |
| `dev.txt` | pytest + ruff (mai nella distribuzione) |
| `locks/windows-py39-runtime.txt` | **freeze esatto** del runtime Windows incluso (fonte di verità, 152 pacchetti) |

## Vincoli non negoziabili

- **`torch < 2.6`**: da 2.6 `torch.load` usa `weights_only=True` e i checkpoint fairseq
  (HuBERT) non si caricano → l'inferenza fallisce. Il doctor controlla e blocca.
- **`fairseq == 0.12.2`** richiede `omegaconf == 2.0.6` → serve `pip < 24.1` per installare.
- **`numpy <= 1.23.5`** e `faiss-cpu 1.7.x`: sono i pin di rvc-python 0.1.5; su Python 3.12
  non esistono wheel cp312 (motivo per cui la 3.0 usa il runtime 3.9).
- **DirectML non supportato**: `torch-directml`/`onnxruntime-*` non servono e sono stati
  spostati in `da_eliminare/runtime-package-trim/` (recuperabili con
  `python tools/trim_runtime.py --restore`).

## Rigenerare i lock

Windows (runtime incluso):

```bat
runtime\python.exe -m pip freeze > requirements\locks\windows-py39-runtime.txt
```

POSIX (dopo `tools/bootstrap.py --install`):

```bash
./runtime/bin/python3 -m pip freeze > requirements/locks/linux-<py>-runtime.txt
```

## Ripristinare il runtime Windows

Il repository non versiona `runtime/` (6,2 GB). Su una macchina Windows:

```bat
python tools\bootstrap.py --restore "da_eliminare\distribuzioni-precedenti\RVC-PortableConMonitoraggio.zip"
python tools\bootstrap.py --check
runtime\python.exe -m app --doctor
```

`restore_runtime_windows.py` estrae solo `Windows/runtime/**` e crea il `.pth` che rende il
runtime portatile rispetto alla radice del progetto.
