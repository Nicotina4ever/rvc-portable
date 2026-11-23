# RVC Portable in REAPER

Azione ReaScript che converte gli item audio selezionati con RVC Portable (voce → voce)
e li importa in una **traccia figlia** sotto la traccia sorgente, come fa UVR per gli stem.

## Installazione

1. Assicurati che RVC Portable sia installato e funzionante (`run.bat` / `./run.sh`).
2. In REAPER: **Actions → Show action list → New action… → Load ReaScript…**
3. Seleziona `Reaper/RVC_Portable.lua`.
4. (opzionale) carica anche `Reaper/RVC_Portable_Settings.lua` per cambiare modello e parametri.

I file `RVC_Portable.lua`, `RVC_Portable_Settings.lua` e `rvc_common.lua` devono restare
nella stessa cartella.

## Prima configurazione

Al primo avvio (o se il modello non è impostato) compare una finestra con:

| Campo | Esempio |
|---|---|
| Python | `K:\AI\rvc-portable\runtime\python.exe` (Linux/macOS: `runtime/bin/python3`) |
| Helper | `K:\AI\rvc-portable\tools\reaper_helper.py` |
| Modello | `K:\AI\rvc-portable\Modelli\Nicola_Spot_Locali.pth` |
| Indice | `K:\AI\rvc-portable\Modelli\added_IVF...index` (opzionale) |
| Pitch | `0` (semitoni, −24…+24) |
| Metodo | `rmvpe` / `harvest` / `crepe` / `pm` |
| Protezione | `0.33` |
| Index rate | `0.3` |
| Formanti | `0` (−12…+12; +1/+2 apre il suono "a denti stretti") |
| Auto-test | `0`/`1`: prova una griglia di parametri su 10 s prima del file intero |
| Secondi auto-test | `10` |
| Suffisso | `_RVC` |

Le impostazioni vengono salvate in REAPER (ExtState) e valgono per tutte le sessioni.

## Cambiare le impostazioni

Le impostazioni salvate **si possono cambiare in qualsiasi momento**, in due modi:

1. **Azione "RVC Portable Settings"** (`RVC_Portable_Settings.lua`): caricarla una volta in
   REAPER (Actions → Load ReaScript) e lanciarla quando vuoi per rivedere modello, indice e
   parametri. Salva e chiude.
2. **Azione principale senza selezione**: lancia `RVC Portable` **senza alcun item/traccia
   selezionata** → si apre direttamente il pannello impostazioni (comodo, niente secondo script
   da caricare).

All'avvio di ogni conversione la console di REAPER mostra la riga
`Modello: … | indice: … | pitch … | metodo …` così vedi sempre con che parametri sta girando.
Se il `.pth` configurato viene spostato o cancellato, l'azione te lo chiede di nuovo.

## Uso

1. Seleziona uno o più **item audio** (o una traccia: vengono presi i suoi item).
2. Esegui l'azione **RVC Portable**.
3. Compare una finestra di avanzamento; a fine lavoro:
   - il file convertito va in `<cartella del sorgente>/RVC_out/<nome>_RVC.wav`;
   - viene creata una traccia `… [RVC]` sotto la sorgente e la traccia originale diventa
     una cartella (`Crea cartella = 1`).

L'operazione è un unico passo di Undo.

## Auto-test

Con `Auto-test = 1`, prima della conversione completa viene convertito un campione di
~10 secondi con una griglia di combinazioni (`rmvpe`/`harvest` × index rate × protezione).
Ogni candidato viene misurato su:

- errore di intonazione (cents),
- rapporto di timbro/centroide (penalizza il suono chiuso),
- energia 4–8 kHz (articolazione/consonanti),
- percentuale di frame sonori e clipping.

La combinazione con il costo più basso viene usata per il file intero. Il report completo
dei candidati viene scritto nella console di REAPER (`Auto-test: {...}`).

Per ascoltare i candidati: i WAV sono in `<cartella output>/_autotest/cand_XX.wav`.

## Uso da riga di comando

Lo stesso helper si può usare senza REAPER:

```bat
runtime\python.exe -B tools\reaper_helper.py ^
  --input "D:\voce.wav" --output-dir "D:\out" ^
  --model "Modelli\Nicola_Spot_Locali.pth" ^
  --index "Modelli\added_IVF...index" ^
  --pitch 0 --method rmvpe --protect 0.33 --index-rate 0.3 ^
  --formant 0 --auto --auto-seconds 10
```

Stampa righe `PROGRESS <0-100> <stadio>`, `AUTO <json>` e infine `RESULT <json>`.

## Problemi comuni

| Sintomo | Causa |
|---|---|
| Nessuna traccia creata | item MIDI o source virtuale: seleziona item con file audio |
| `ERRORE: modello non trovato` | percorso del `.pth` sbagliato nella configurazione |
| La conversione parte ma è lenta | prima esecuzione: carica il modello (~5–10 s) |
| Auto-test lentissimo | abbassa i secondi a 5 o usa solo `rmvpe` |
| Voce metallica | prova `formant` +1/+2, `protect` 0.4–0.5, `index_rate` 0.2–0.3 |

## Linux / macOS

I percorsi nel dialog sono stringhe: su Linux/macOS usa `/home/.../runtime/bin/python3`.
Il resto funziona allo stesso modo (REAPER su macOS richiede il permesso di eseguire
script Lua: preferenze → ReaScript → abilita).
