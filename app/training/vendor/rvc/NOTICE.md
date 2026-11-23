# NOTICE — codice di training vendorizzato

`app/training/vendor/rvc/` contiene una copia adattata della pipeline di training di

> **RVC1006Nvidia** — <https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI>
> Copyright (c) 2023 liujing04, 源文雨, Ftps — licenza MIT.

Sono stati copiati/adattati i moduli necessari a girare sul runtime portatile di
RVC Portable (Python 3.9, torch 2.0.0+cu118, fairseq 0.12.2).

## Patch applicate

| File | Modifica |
|---|---|
| `_boot.py` | bootstrap per il runtime con `python39._pth`: aggiunge la cartella vendor a `sys.path` e lancia il modulo con `runpy` |
| `infer/hubert.py` | riscritto: HuBERT via **fairseq** (`hubert_base.pt` del runtime) al posto di Transformers |
| `infer/audio.py` | riscritto: `soundfile` + PyAV, senza `ffmpeg-python`/torchaudio |
| `configs/config.py` | ridotto alle regole di scelta device/precisione |
| `i18n/i18n.py` | no-op (nessun catalogo lingue) |
| `tools/cuda_graph.py` | passthrough (CUDA graph non usato) |
| `tools/summary.py` | `SummaryWriter` minimale che scrive JSONL invece di TensorBoard |
| `tools/progress.py` | messaggi ASCII e `PROGRESS x y` stabile |
| `train/train.py` | `SummaryWriter` sostituito; marker `RVC_STEP`/`RVC_EPOCH` per il parsing |
| `train/preprocess.py` | UTF-8 forzato su stdout e marker `PROGRESS` |
| `train/process_ckpt.py` | output pesi in `RVC_TRAIN_WEIGHTS_DIR` |
| `train/dataset/extract_f0.py` | riscritto: RMVPE/parselmouth, output `.npy`, niente DirectML |
| `train/dataset/extract_hubert_feature.py` | riscritto: feature 256/768 via fairseq |

## Cosa non è stato copiato

UI Gradio, separazione UVR, realtime, DirectML, i18n completa e gli asset grafici.
Gli asset `logs/mute` (silenzio di riferimento per stabilizzare le prime epoche) sono
inclusi in `assets/mute/` (~1,3 MB).

Le licenze MIT originali restano valide; questo NOTICE va mantenuto in ogni
redistribuzione.
