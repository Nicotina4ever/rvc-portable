# Cura del dataset: dal materiale grezzo a un modello professionale

Un modello RVC “super ottimale” non nasce dal parametro magico: nasce da **dataset pulito,
coerente e vario**. Questa guida spiega il metodo e lo strumento incluso.

## 1. Cosa rovina un modello

| Problema | Effetto sulla voce generata |
|---|---|
| Musica, jingle, sigle sotto la voce | il modello impara il mix, non la voce: timbro sporco e “metallico” |
| Riverbero / stanza | voce lontana, articolazione impastata, effetto “denti stretti” |
| Rumore di fondo, ventole, traffico | fruscio e sibilo costanti nel modello |
| Clipping / volume troppo alto | distorsione appresa, consonanti dure |
| File troppo corti o silenzi lunghi | poco materiale utile, prosodia povera |
| Stessa frase ripetuta | overfitting: il modello “inventa” su frasi nuove |
| Dataset troppo uniforme (un solo tono) | poca espressività, voce piatta |

## 2. Analisi: `tools/curate_dataset.py`

Lo strumento analizza ogni file **senza modificare gli originali** e produce:

- `report.json` — metriche complete per file;
- `report.csv` — tabella apribile in Excel;
- `report.md` — riepilogo leggibile;
- `clean/` — file promossi per il training;
- `review/` — file dubbi da ascoltare;
- `validation/` — file tenuti fuori dal training per i test.

Esempio (solo analisi, nessuna copia):

```bat
runtime\python.exe -B tools\curate_dataset.py ^
  --source "Modelli\Dataset_Spot_Locali" ^
  --out "data\reports\Dataset_Spot_Locali_report" --dry-run
```

Esempio completo (copia + cartelle pulite):

```bat
runtime\python.exe -B tools\curate_dataset.py ^
  --source "Modelli\Dataset_Spot_Locali" ^
  --out "Modelli\Dataset_Spot_Locali_pulito" ^
  --rewrite --trim-silence --resample 48000 --validation 5
```

`--rewrite` decodifica e riscrive WAV 48 kHz mono, taglia i silenzi ai bordi e limita i picchi.
`--validation 5` mette da parte 5 file promossi: serviranno per l’auto-test su materiale **mai
visto** durante il training.

### Metriche calcolate

| Metrica | Cosa indica | Soglia tipica |
|---|---|---|
| `duration_s` | durata del file | ≥ 3 s (ideale 10–60 s) |
| `rms_dbfs` | loudness media | −30…−14 dBFS |
| `peak_dbfs` | picco | vicino a 0 dB ma senza saturare |
| `clipping` | frazione di campioni saturi | < 1% |
| `silence_ratio` | frazione di silenzio | < 60% |
| `flatness` | “piattezza” spettrale (rumore) | < 0.30 |
| `beat_strength` | periodicità ritmica (musica) | più alto = probabile musica |
| `music_likelihood` | euristica musica/jingle | < 0.45 |
| `quality` | punteggio 0–100 | > 80 |

L’euristica musica è **prudente**: usa la periodicità del ritmo, non la sola energia percussiva
(anche la voce ha consonanti). Musica senza ritmo (archi, pad) può sfuggire: per questo i file
dubbi finiscono in `review/`, non vengono cancellati.

## 3. Cosa fa il classificatore

- **reject** — file non decodificabile, troppo corto, clipping elevato, segnale bassissimo,
  duplicato esatto.
- **review** — musica probabile, molto silenzio, rumore, durata anomala: **va ascoltato**.
- **keep** — entra in `clean/` (o `validation/`).

I duplicati esatti usano SHA-256. I “simili” (MFCC) sono **disattivati** per default perché due
spot diversi con la stessa voce possono somigliarsi; si attivano con `--near-dupes` sapendo il
rischio.

## 4. Workflow consigliato per uno spot professionale

1. **Audit** con `--dry-run`; apri `report.md` e guarda quanti file finiscono in `review`.
2. **Ascolta** i file in `review/`: tieni quelli con la voce che vuoi clonare, scarta jingle e
   musica. Se la musica è tanta, meglio ritagliare le sole parti parlate (Audacity/REAPER).
3. **Pulisci** con `--rewrite --trim-silence --validation 5`.
4. **Bilanciamento**: 15–30 minuti di parlato vario battono 2 ore di spot tutti uguali. Per il
   timbro servono frasi diverse, domande, numeri, nomi; non solo lo stesso slogan.
5. **Training** con preset Bilanciato (prova) o Qualità (definitivo).
6. **Auto-test** su un file di `validation/` (REAPER: Auto-test 1; oppure
   `tools/reaper_helper.py --auto`): confronta index rate, protezione, formant e scegli a orecchio
   tra i candidati in `_autotest/`.
7. **Test finale** su una frase mai vista: se “inventa” parole, il dataset è troppo piccolo o
   troppo uniforme; aggiungi materiale.

## 5. Limiti

- Le metriche sono euristiche: non sostituiscono l’ascolto.
- Il rilevatore di musica non riconosce tutti i generi; controlla sempre `review/`.
- Il taglio silenzi è automatico ma conservativo.
- Non normalizzare troppo: il preprocess RVC normalizza già; `--rewrite` limita solo i picchi.

## 6. Dataset attuale (23/11/2026)

`Modelli/Dataset_Spot_Locali`: **502 file, 165,7 minuti, 48 kHz**. È materiale reale di spot, quindi
 contiene spesso musica: il report di cura indica quali file usare per un modello pulito.
Il report generato è in `data/reports/Dataset_Spot_Locali_20261123/` (locale, non versionato).
