# Ponte Android ↔ PC (Dropbox)

L'anima del progetto è questa: **registri e monti sul telefono, il PC converte, il risultato
torna sul telefono**. Nessuna GPU sul telefono, nessun token sul PC: basta il **client Dropbox
desktop** sul computer e una cartella condivisa (`Dropbox/TestRVC`).

```text
  TELEFONO (mini-DAW)                 DROPBOX (sincronizzato)                 PC (RVC Portable)
  ─────────────────────               ───────────────────────                 ──────────────────
  registra / taglia / mixa
  export WAV  ───────────────────▶  TestRVC/AudioIn/nome.wav  ─────────────▶  monitor della cartella
  config.json (parametri)  ──────▶  TestRVC/config.json      ─────────────▶  hot-reload config
                                                                              motore RVC (CUDA/CPU)
  importa nel progetto  ◀─────────  TestRVC/AudioOut/nome.wav ◀─────────────  scrive stesso nome
```

## Lato telefono (app `rvc-portable-android`)

1. Installa l'APK release.
2. Inserisci la **App Key Dropbox** e connetti l'account (token salvato solo sul telefono).
3. Registra una traccia nella mini-DAW, applica tagli/effetti, poi usa **CONVERTI CON RVC**.
4. L'app:
   - scarica `config.json` e `modelli.txt` dalla cartella condivisa;
   - carica il WAV in `AudioIn`;
   - attende (fino a ~3 minuti) `AudioOut/<stesso nome>.wav` e lo importa nel mixer.

I percorsi predefiniti dell'app sono:

```text
/TestRVC/AudioIn
/TestRVC/AudioOut
/TestRVC/config.json
/TestRVC/modelli.txt
```

## Lato PC (RVC Portable 3.0)

1. Installa **Dropbox desktop** sul PC e accedi con lo stesso account.
2. Apri l'app → tab **Cloud** → sezione **Cartella condivisa con l'app Android**.
3. Premi **Rileva Dropbox**: viene proposta `…\Dropbox\TestRVC`.
4. Premi **Attiva preset**. In un colpo:
   - crea `AudioIn` e `AudioOut` (se mancano);
   - imposta le cartelle input/output dell'app su quelle condivise;
   - genera `modelli.txt` con i modelli trovati in `Modelli/` (e nelle cartelle extra);
   - scrive `config.json` compatibile con Android;
   - attiva hot-reload config e **avvio automatico del monitoraggio** all'apertura.
5. Chiudi e riapri l'app (o avvia il monitor dalla Dashboard): da questo momento ogni file che
   arriva in `AudioIn` viene convertito e scritto in `AudioOut` **con lo stesso nome**.

Non serve configurare OAuth sul PC: il PC usa solo il filesystem sincronizzato da Dropbox.

### Verifica

```bat
runtime\python.exe -m app --doctor
```

Il check **Ponte Android/Dropbox** deve risultare `OK` (cartelle, `modelli.txt` e diritti di
scrittura). Dalla tab Cloud puoi sempre premere:
- **Sincronizza modelli** — rigenera `modelli.txt` (dopo aver aggiunto modelli);
- **Applica config** — forza la rilettura di `config.json`.

## Controllo remoto del PC (senza VPN)

L'app Android può cambiare i parametri del PC anche quando sei lontano: la scheda **Cloud →
Controllo PC** mostra lo stato del PC e permette di inviare una nuova configurazione.

1. Il PC scrive `TestRVC/status.json` ogni ~5 secondi (heartbeat) con:
   - `providers.engine` (motore disponibile, device, GPU, modello caricato),
   - `providers.queue` (queued/running/done/failed),
   - `providers.watcher` (monitor attivo e cartella),
   - `providers.config` (ultima config applicata, errori),
   - `audio` (pitch, metodo, protect, index rate, modello corrente).
2. Il telefono legge `status.json` da Dropbox e mostra **ONLINE/OFFLINE**, modello, coda e ultima
   config applicata.
3. Dal pannello puoi modificare pitch, formant, index rate, protezione, metodo F0 e modello, poi
   premere **INVIA AL PC**: l'app scrive `config.json`; il PC lo applica con hot-reload (~2 s) e
   aggiorna `status.json`. **LEGGI CONFIG** riporta nel telefono la config attualmente sul PC.

Tutto passa dal client Dropbox desktop: **nessuna porta aperta sul PC, nessuna VPN, nessun token
sul PC**. Il vecchio `Modifica Parametri.html` non serve più: il controllo remoto è dentro l'app e
valida i parametri (metodi supportati, range, modelli esistenti). Se preferisci, il file HTML può
restare come archivio; non viene più usato dal flusso.

## Formato dei file condivisi

### `modelli.txt`

Una riga per modello, generata dal PC:

```text
# commento
Nicola-Spot2 | K:\AI\rvc-portable\Modelli\Nicola-Spot2.pth | K:\AI\rvc-portable\Modelli\added_IVF1456_Flat_nprobe_1_Nicola-Spot2_v2.index
```

L'app Android mostra il nome e, alla conversione, invia nel `config.json` i percorsi Windows del
`.pth` e dell'`.index`: il PC li usa direttamente. Rigeneralo ogni volta che aggiungi modelli
(Dropbox o `Modelli/`).

### `config.json`

Il PC scrive una forma **ibrida**: schema v3 annidato (per sé) + chiavi piatte che l'app Android
legge (`pitch`, `method`, `protect`, `index_rate`, `model_path`, `index_path`).
Quando il telefono scrive la sua versione piatta, il PC la applica automaticamente e riscrive il
file ibrido, così le due parti restano allineate.

Esempio delle chiavi piatte:

```json
{
  "input_dir": "/TestRVC/AudioIn",
  "output_dir": "/TestRVC/AudioOut",
  "model_path": "K:\\AI\\rvc-portable\\Modelli\\Nicola-Spot2.pth",
  "index_path": "K:\\AI\\rvc-portable\\Modelli\\added_IVF1456_Flat_nprobe_1_Nicola-Spot2_v2.index",
  "pitch": 0,
  "method": "rmvpe",
  "protect": 0.33,
  "index_rate": 0.3
}
```

I percorsi `/TestRVC/...` scritti dal telefono vengono tradotti dal PC in
`<cartella condivisa>\AudioIn|AudioOut`; quelli Windows del modello vengono applicati solo se il
file esiste davvero sul PC (altrimenti la chiave viene ignorata e lo si vede nei log).

## Nomi dei file e tempi

- L'output ha **lo stesso nome dell'input** (es. `telefono.wav` → `AudioOut/telefono.wav`).
  Se riconverti lo stesso nome, il file precedente viene sostituito.
- Primo job dopo l'avvio: ~20–30 s (warm-up del motore + caricamento modello). Successivi: pochi
  secondi per pochi secondi di audio (RTF ≈ 0,3 su RTX 4060 Ti).
- L'app attende fino a ~3 minuti per file; per file molto lunghi conviene convertirli dal PC.

## Risoluzione problemi

| Sintomo | Causa | Rimedio |
|---|---|---|
| Il telefono dice "in attesa" e non arriva nulla | Dropbox sul PC non sincronizza `TestRVC` | apri Dropbox desktop, verifica account e cartella selettiva; controlla `AudioIn` locale |
| Il file arriva in `AudioIn` ma non viene convertito | monitor non attivo | Dashboard → Avvia monitoraggio; oppure riattiva il preset (avvio automatico) |
| Output assente in `AudioOut` | conversione fallita | guarda `data/logs/engine.log` e `app.log`; la Dashboard mostra lo stato del job |
| `config.json` del telefono non applicato | hot-reload spento o percorso errato | tab Cloud → verifica "Percorso locale o NAS" = `…\TestRVC\config.json`, hot reload attivo; premi **Applica config** |
| `modelli.txt` non aggiornato | modelli aggiunti dopo il preset | **Sincronizza modelli** |
| Modello "sconosciuto" sul telefono | `modelli.txt` elenca percorsi del PC | rigenera dal PC con i modelli presenti; il telefono usa i percorsi del PC, non copia i `.pth` |
| Accenti/caratteri strani nei nomi | nomi file con `?`, `:` ecc. | usa nomi semplici (lettere, numeri, `-`, `_`) |
| In Dropbox compaiono file `config (Copia in conflitto …)` | due scritture ravvicinate (PC + telefono o altro PC) | tieni `config.json`, elimina le copie in conflitto; il PC ora riscrive solo quando serve e ritenta se Dropbox tiene il file occupato; evita di modificare `config.json` da più dispositivi insieme |
| Restano file `config.json.tmp-*` | scrittura interrotta/processo chiuso | vengono rimossi automaticamente al successivo **Sincronizza modelli**/salvataggio; puoi cancellarli a mano |

Log: `data/logs/app.log` (backend), `data/logs/engine.log` (motore), `data/logs/stdout.log`.

File preesistenti nella cartella (`config_port.json`, `config_instore.json`,
`Modifica Parametri.html`) **non vengono toccati**: sono della vecchia configurazione e possono
restare come riferimento. Il PC riscrive solo `config.json`, `modelli.txt` e le cartelle
`AudioIn`/`AudioOut`.

## Note tecniche

- Modulo PC: `app/android_bridge.py` (rilevamento Dropbox, `modelli.txt`, config ibrido,
  `ConfigSync`, retry di scrittura per i lock del client Dropbox); rotte `/api/android*`; preset in
  `web/js/views/cloud.js`.
- Hot-reload: `ConfigSync` osserva `cloud.local_path` ogni ~2 s e applica solo se il contenuto
  cambia (hash); riscrive la forma ibrida solo quando i valori differiscono, per ridurre le
  copie in conflitto di Dropbox.
- Il PC non effettua chiamate Dropbox: la sincronizzazione è del client desktop. Se preferisci
  evitare il client, resta disponibile l'integrazione OAuth della tab Cloud (opzione avanzata).
- Il motore Android (ONNX) e il motore PC (PyTorch) restano indipendenti: il telefono non ha
  bisogno di `.onnx` per usare la conversione remota.
