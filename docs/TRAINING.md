# Addestramento modelli RVC

RVC Portable può **creare** un modello `.pth` + indice `.index` partendo da un dataset
audio, usando la stessa pipeline di RVC (RVC1006Nvidia, licenza MIT, adattata al runtime
portatile). Non serve installare RVC a parte.

> Il training richiede una **GPU NVIDIA** con almeno 4 GB di VRAM e ~2 GB liberi su disco.
> Su macOS il training parte ma gira su CPU: è lentissimo, quindi è sconsigliato.
> Su Linux con `--profile cuda118` funziona come su Windows.

## 1. Preparare il dataset

Requisiti qualitativi:

| Voce | Consigliato |
|---|---|
| Durata totale | 15–30 minuti (minimo 8) |
| Formato | WAV 44.1/48 kHz, oppure MP3/M4A di buona qualità |
| Contenuto | Solo la voce da clonare, senza musica o rumore di fondo |
| Pulizia | Tagliare silenzi lunghi, respiri forti, frasi sovrapposte |
| File | Il nome non conta; il dataset può essere una cartella o uno ZIP |

La cartella `Modelli/Dataset_Spot_Locali` è un esempio reale di spot già montati: va bene
come base, ma prima del training conviene togliere musica e jingle. Metodo e strumento:
**[DATASET.md](DATASET.md)** (`tools/curate_dataset.py`).

## 2. Avviare l'addestramento

1. Apri l'app e vai su **Addestramento**.
2. Scegli la cartella (o lo ZIP) del dataset con **Cartella** / **ZIP**.
3. Premi **Analizza dataset**: vedrai file validi, durata totale, sample rate e avvisi.
4. Dai un **nome** al modello (diventa il nome del `.pth` in `Modelli/`).
5. Scegli un preset:
   - **Veloce** — 120 epoche, per prove;
   - **Bilanciato** — 250 epoche, uso normale;
   - **Qualità** — 400 epoche, dataset lunghi e puliti.
6. **Avvia training**.

Il job passa da questi stadi (visibili nella card di avanzamento):

| Stadio | Cosa fa |
|---|---|
| Preparazione dataset | copia gli audio e valida durata/leggibilità |
| Verifica pesi base | controlla `hubert_base.pt`, `rmvpe.pt` e i pre-addestrati G/D |
| Taglio e ricampionamento | slice da ~3,7 s, normalizzazione, 16 kHz per le feature |
| Estrazione F0 | RMVPE (consigliato) o Parselmouth (pm) |
| Estrazione feature HuBERT | 768 dimensioni per RVC v2 (256 per v1) |
| Training | GAN generatore/discriminatore con i pesi pre-addestrati |
| Indice FAISS | crea l'indice per il retrieval (index rate) |
| Salvataggio | copia `.pth` e `.index` in `Modelli/` |

Alla fine il modello è già selezionabile in **Configurazione** e nella conversione.
Il pulsante **Prova il modello** accoda una conversione di test.

## 3. Parametri avanzati

| Parametro | Default | Note |
|---|---|---|
| Sample rate | 48 kHz | 40 kHz usa la famiglia v1; 32 kHz per voci molto basse |
| Versione | v2 | v1 solo per compatibilità con modelli vecchi |
| F0 | attivo | migliora canto e intonazione; disattivalo solo per parlato piatto |
| Metodo F0 | rmvpe | `pm` è più veloce ma meno preciso |
| Epoche | 250 | più epoche = più definizione, ma rischio overfitting |
| Batch size | 6 | abbassalo se va in OOM (4 o 2) |
| Salva ogni | 20 | crea checkpoint intermedi |

I file intermedi restano in `data/training/jobs/<id>/`; puoi riprendere un job fallito con
**Riprendi** o eliminarlo con **Elimina**.

## 4. Dove finiscono i file

```
data/training/
├─ assets/pretrained_v2/     # G/D pre-addestrati (scaricati una volta)
├─ jobs/<id>/dataset/raw/    # copia del dataset
├─ jobs/<id>/logs/<nome>/    # feature, checkpoint, config
└─ jobs/<id>/weights/        # .pth prodotti dal training
Modelli/
├─ <nome>.pth
└─ added_IVF..._<nome>_v2.index
```

I pesi pre-addestrati G/D vengono cercati in: cartella configurata, `data/training/assets`,
installazioni RVC locali note (`D:\AI\RVC1006Nvidia\assets`, `K:\AI\ultimate-rvc\...`).
Se mancano e il download è abilitato, vengono scaricati da HuggingFace
(`lj1995/VoiceConversionWebUI`).

## 5. Consigli sulla qualità

- **Dataset pulito batte qualsiasi parametro.** Rumore, musica e riverbero entrano nel modello.
- 15–30 minuti di parlato **variato** (frasi diverse, non la stessa frase ripetuta).
- Se la voce esce "chiusa" o metallica: abbassa `index_rate` (0.2–0.3), alza `protect`
  (0.33–0.5), prova `formant` +1/+2 in **Voce → Parametri**.
- Se il modello "inventa" pronuncia: dataset troppo corto o troppo uniforme; aggiungi materiale.
- Il modello definitivo va testato su una frase **mai vista** durante il training.

## 6. Riferimenti tecnici

- Codice vendorizzato in `app/training/vendor/rvc/` (fork MIT di RVC1006Nvidia, con patch
  documentate in `NOTICE.md`).
- HuBERT: fairseq `hubert_base.pt` del runtime (stesso usato dall'inferenza).
- F0: `rmvpe.pt` del runtime.
- Il training gira in processi separati: un crash non blocca l'app.
- Mentre il training è attivo, la coda di conversione viene messa in pausa per evitare OOM.


## 7. Checkpoint, confronto e rifinitura

- **Backup**: prima di sovrascrivere un modello in `Modelli/`, il vecchio `.pth` viene copiato in
  `Modelli/backups/<nome>_<data>.pth`. Anche il fine-tune salva sempre una copia del modello di
  partenza.
- **Confronto checkpoint**: a fine training i `.pth` salvati (uno ogni `Salva ogni N epoche`)
  vengono provati su un campione di 10 s con due passate; la UI mostra il punteggio e il
  **migliore diventa il modello finale**.
- **Campione di test**: scegli un file di `validation/` (o un audio di ~10 s mai usato nel training)
  nel campo "Campione di test": serve a confrontare i checkpoint in modo onesto.
- **Rifinitura**: il campo "Rifinisci un modello esistente" parte da un `.pth` già addestrato.
  Usa **10–50 epoche**, lo stesso sample rate/versione del modello e un dataset pulito; troppe
  epoche rischiano di dimenticare la voce originale (catastrophic forgetting).
- **Un solo training alla volta**: il backend rifiuta un secondo job finché il primo è in corso o
  in coda. Annulla o attendi prima di avviarne un altro.
- **Riprendere/continuare**: "Riprendi" sui job annullati/falliti riparte dallo stadio rimasto;
  "Continua training" sui job completati chiede quante epoche aggiungere e riparte dall'ultimo
  checkpoint. Entrambi richiedono la cache del job (se l'hai pulita, il bottone avvisa che serve
  un nuovo job o il fine-tune dal modello).

## 8. Pulire la cache di un training

Nella card del job (o con **"Pulisci cache job chiusi"**) puoi eliminare i file temporanei:
dataset copiato, feature `0_gt_wavs`/`1_16k_wavs`/`2a_f0`/`2b-f0nsf`/`3_feature*`, checkpoint
intermedi, cartella `eval/` e output temporanei. Restano il log e il modello finale in `Modelli/`.

Dopo la pulizia il job **non è più riprendibile** senza rifare il training: è il compromesso per
tenere la cartella ordinata. L'operazione chiede conferma e mostra quanti MB ha liberato.
