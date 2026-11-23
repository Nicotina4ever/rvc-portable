# Stato del progetto — 23 novembre 2026

Questo documento è il punto di riferimento per capire **cosa è pronto, cosa è stato testato e
cosa resta da verificare**. Aggiornalo a ogni rilascio.

## Versioni

| Componente | Versione | Release |
|---|---|---|
| RVC Portable (PC) | **3.3.7** | <https://github.com/Nicotina4ever/rvc-portable/releases/tag/v3.3.7> |
| Runtime Windows | 3.0.0 (invariato) | <https://github.com/Nicotina4ever/rvc-portable/releases/tag/runtime-v3.0.0> |
| RVC-Droid (Android) | **4.0** | <https://github.com/Nicotina4ever/rvc-droid/releases/tag/v4.0> |
| Motore | rvc-python 0.1.5 + fairseq 0.12.2 + torch 2.0.0+cu118 | — |

## Cosa è pronto

### PC

- **Addestramento RVC** (tab Addestramento): da cartella/ZIP a `.pth` + `.index`, con preset,
  avanzamento per stadio, log, annulla/riprendi e test del modello.
  Guida: [TRAINING.md](TRAINING.md).
- **REAPER**: `Reaper/RVC_Portable.lua` converte gli item selezionati e li importa in una traccia
  figlia (`RVC_out/`), con auto-test e formant. Guida: [../Reaper/README.md](../Reaper/README.md).
- **Auto-test parametri** (`app/tuning/auto_tune.py`, `--auto` dell'helper): griglia
  metodo/index/protect misurata su intonazione, timbro, articolazione e clipping.
- **Formant shift** (−12…+12) via pyworld, disponibile su PC, Android e REAPER.
- **Indice manuale per modello**: dalla vista Modelli puoi assegnare qualsiasi `.index` a un
  `.pth`, anche con nome diverso; l'elenco degli indici è sempre disponibile.
- **Log di training a fine pagina**: la vista Addestramento mostra le ultime righe con
  auto-scroll, copia e scelta del numero di righe.
- **Confronto checkpoint** e **rifinitura di un modello esistente** con backup automatico.
- **Un solo training attivo alla volta**: il backend rifiuta un secondo job e la UI mostra
  il badge "TRAINING ATTIVO"; i job annullati si possono eliminare dalla lista.
- **Suggerimenti in GUI**: pulsanti "?" accanto ai campi di Addestramento, Configurazione e
  Modelli, con consigli pratici (F0, epoche, indice manuale, formant, dataset).
- **Menu adattivo**: sotto i 1440 px la navigazione si compatta dietro un pulsante hamburger
  (mostra/nascondi), evitando sovrapposizioni con stato/lingua/tema.
- **System tray Windows**: icona con menu Mostra, Avvia/Ferma monitoraggio, Ferma monitoraggio
  e motore, Scarica motore, Apri cartelle, Esci. Chiudendo la finestra l'app resta attiva.
- **Stile più sobrio**: meno gradienti e aloni neon su pulsanti, progress e stati attivi.
- **GUI**: pulsanti "?" compatti; menu sempre visibile su due righe (niente hamburger);
  **Continua training** sui job completati (epoche extra dal checkpoint) e **Riprendi**
  su quelli interrotti; pulizia cache con avviso di non-ripresa.
- **Fine-tune ben visibile** nel form Addestramento e **pulizia cache** per singolo job o per
  tutti i job chiusi, con conferma: libera dataset copiato, feature, checkpoint intermedi e
  output temporanei; il modello finale in Modelli/ resta.
- **Monitor silenzioso**: niente avvio automatico, log di ciclo a DEBUG, stop su inattività.
- **Distribuzione Linux/macOS**: archivi dedicati, `setup.sh`/`setup.command`, download pesi base.

### Android

- RVC-Droid 4.0: schermate **Registra / Tracce / Voce**, menu **Altro**, rotazione libera e layout
  a due colonne in orizzontale.
- **Gobbo sopra il video** (script sincronizzato alla riproduzione).
- **Regioni**: pulsante REGIONI in Tracce → export locale o batch RVC via Dropbox.
- **Formant** nella configurazione remota.

## Cosa è stato verificato

| Verifica | Esito |
|---|---|
| Test PC (`pytest`) | **241 passed, 1 skipped** |
| Ruff | pulito |
| Training end-to-end | sì: preprocess → F0 → HuBERT → train 1 epoca → indice, `.pth` + `.index` prodotti |
| REAPER portable | sì: item convertito, `RVC_out/test_RVC.wav` creato, traccia figlia “Voce [RVC]” |
| Auto-test su voce reale | sì: metriche sensate (F0 ~238 cents, centroide ~1.01, HF ~1.02) |
| Formant su conversione reale | sì (`--formant 2`) |
| Build APK release | sì, firmato (versionCode 8, versionName 4.0) |
| Dataset spot | 502 file, **165,7 min**, 48 kHz, pronto (1 file <3 s ignorato) |
| Cura dataset (campione) | analisi qualità/musica/duplicati verificata su 12 file |
| Dataset pulito generato | `Modelli/Dataset_Spot_Locali_pulito`: 497 training + 5 validation, 165,7 min |
| Confronto checkpoint | due passate su campione, scelta del migliore (test su checkpoint reale) |
| Fine-tune | conversione `.pth` e backup automatico verificati |

## Cosa NON è stato verificato

- APK 4.0 su **telefono reale** (nessun device ADB collegato durante lo sviluppo).
- Archivi Linux/macOS su **VM** (li testerà l'utente).
- **Training completo** del dataset spot: 2h45m di audio, durerebbe ore di GPU. Il test ha usato
  un dataset sintetico da 12 s per validare la pipeline, non la qualità del modello.

## Ottimizzazione e spazio

- `tools/cleanup_project.py` sposta gli artefatti rigenerabili in `da_eliminare/`:
  - `--dry-run` (default): mostra il piano;
  - `--apply`: esegue;
  - `--report`: solo spazio occupato.
- Non tocca mai `Modelli/`, `Progetto/`, `runtime/`, `Reaper/portable/` e `data/state/`.
- Al 23/11/2026 la quarantena contiene ~**4,8 GB** (runtime 3.0.0 e artefatti di test); può essere
  svuotata quando vuoi (la cartella `da_eliminare/` non è versionata: contiene un README locale).

Spazio tipico del progetto dopo la pulizia: ~8,5 GB totali, di cui `runtime/` 5,7 GB e `Modelli/`
2,6 GB (dati dell'utente). Il repository Git resta leggero (~2,7 MB di `.git`).

## Prossimi passi consigliati

1. Provare l'APK 4.0 su un telefono e l'archivio Linux/macOS su VM.
2. Con il dataset spot: creare il modello con preset **Qualità** (o Bilanciato per una prova),
   togliendo musica/jingle; poi usare l'auto-test per scegliere `index_rate`/`protect`/formant.
3. Valutare restauro audio / TTS per le parole dove il modello fatica (progetto separato).

## Punto di arrivo (23/11/2026)

- App **3.3.2** in esecuzione con una sola istanza; nessun training attivo.
- **Dataset pulito**: `Modelli/Dataset_Spot_Locali_pulito` (497 training + 5 validation, 165,7 min,
  WAV 48 kHz mono). L'originale in `Modelli/Dataset_Spot_Locali` è intatto.
- **Spazio**: `runtime/` 5,7 GB, `Modelli/` 3,5 GB (originale + pulito), `data/` ~0,02 GB,
  `da_eliminare/` ~0,45 GB (cancellabile quando vuoi), `dist/` solo gli archivi 3.3.2.
- **GUI**: suggerimenti "?" su Addestramento/Configurazione/Modelli, log di training con
  auto-scroll, confronto checkpoint e fine-tune con backup.
- **Un solo training alla volta**: il backend risponde `409 training_busy`; i job annullati
  possono essere eliminati dalla lista.
- **Release**: [PC 3.3.7](https://github.com/Nicotina4ever/rvc-portable/releases/tag/v3.3.7) ·
  [Android 4.0](https://github.com/Nicotina4ever/rvc-droid/releases/tag/v4.0).
