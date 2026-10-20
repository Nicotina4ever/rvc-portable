# Istruzioni pratiche — RVC Portable e RVC-Droid

Ultimo aggiornamento: 20 ottobre 2026.

## 1. Stato attuale (già online)

Non devi fare nulla per pubblicare: i repository e le release esistono già.

| Cosa | Link |
|---|---|
| Sorgenti PC | <https://github.com/Nicotina4ever/rvc-portable> |
| Sorgenti Android | <https://github.com/Nicotina4ever/rvc-droid> |
| Release PC 3.0 | <https://github.com/Nicotina4ever/rvc-portable/releases/tag/v3.0.0> |
| Runtime PC (Windows) | <https://github.com/Nicotina4ever/rvc-portable/releases/tag/runtime-v3.0.0> |
| APK Android 2.1 | <https://github.com/Nicotina4ever/rvc-droid/releases/tag/v2.1> |

Il runtime Windows (3,5 GB in 2 parti) è già caricato e `install.conf` punta alla release
corretta. Ho provato un'installazione **da clone pulito**: `setup.bat` scarica le parti, verifica
lo SHA-256, estrae il runtime e la diagnostica finale dà solo i WARN attesi (configurazione
Dropbox/modello ancora da scegliere).

## 2. Installare per usare il programma

### PC (Windows)

```bat
git clone https://github.com/Nicotina4ever/rvc-portable.git "D:\App\RVC-Portable"
cd /d "D:\App\RVC-Portable"
setup.bat
run.bat
```

In alternativa, dalla pagina Releases scarica lo zip sorgente e il runtime, ma `setup.bat` fa
tutto da solo. Al primo avvio: **Cloud → Rileva Dropbox → Attiva preset**, poi scegli il modello
`.pth` (e l'eventuale `.index`) del PC. Non serve convertire nulla in ONNX.

### Android

Installa `RVC-Droid-2.1.apk` dalla release v2.1. Se hai già installata una versione con la stessa
firma, si aggiorna sopra; se il telefono rifiuta l'installazione, disinstalla la vecchia versione
(i modelli non sono nell'APK, non perdi nulla).

Nel telefono: **Cloud → RVC remoto**, inserisci il token Dropbox (una volta), sincronizza
`modelli.txt`, poi registra/monta e usa **CONVERTI CON RVC (DROPBOX)**. La conversione avviene sul
PC con i `.pth` originali: **niente ONNX, niente modelli da copiare sul telefono**.

## 3. Aggiornare il progetto (Git)

Serve solo se modifichi il codice e vuoi pubblicare le modifiche.

Prima configurazione, una volta sola:

```bat
git config --global user.name "Nicotina4ever"
git config --global user.email "Nicotina4ever@users.noreply.github.com"
git config --global credential.helper manager
```

Poi, per ogni modifica, il modo semplice è **un solo comando** (o doppio click sul file):

```bat
PUBBLICA.bat
```

Con un messaggio tuo:

```bat
PUBBLICA.bat -Message "Descrizione breve della modifica"
```

Lo script fa tutto in un'unica richiesta: controlla il branch `main`, imposta identità e Credential
Manager se mancano, esegue `git add -A`, crea il commit solo se ci sono modifiche e fa il push.
Usa il token già salvato, quindi non dovrebbe più chiedere permessi a ogni push: al primo push
autorizza GitHub una volta nel browser.

Per pubblicare **entrambi** i repository (PC + Android):

```bat
PUBBLICA-TUTTO.bat
```

Per vedere cosa farebbe senza pubblicare:

```bat
PUBBLICA.bat -DryRun
```

Se preferisci i comandi manuali, sotto il cofano lo script esegue:

```bat
git add -A
git commit -m "Descrizione breve della modifica"
git push
```

La prima `git push` apre il browser (GitHub login): autorizza una volta sola. **Se chiede permessi
di continuo**: chiudi le finestre di login già aperte, esegui un solo comando per volta e non
lanciare due push in parallelo; in alternativa usa **GitHub Desktop**. Git Credential Manager non
è un virus: è il programma che salva il token di GitHub e ogni tanto lo fa scadere.

### Se un push si blocca

```bat
git status
git log --oneline -3
```

- se ci sono commit locali non pushati: `git push`
- se non ci sono modifiche: non c'è nulla da fare
- per annullare un push bloccato: `Ctrl+C`, poi riprova un comando alla volta

## 4. Pubblicare una nuova versione

### Nuovo APK Android

```bat
cd /d "K:\AI\Android\rvc-portable-android"
set JAVA_HOME=F:\Android\jdk-17.0.12
gradlew.bat :app:testDebugUnitTest :app:assembleRelease :app:copyRelease
```

Poi:

1. crea una release con tag `vX.Y` nella pagina GitHub → Releases → «Draft a new release»;
2. allega `app-release.snapshot.apk` (rinominalo `RVC-Droid-X.Y.apk`);
3. aggiorna il link APK nel `README.md` del repo Android.

### Nuovo runtime PC

Il runtime si costruisce con:

```bat
runtime\python.exe -B tools\build_runtime_asset.py --repo Nicotina4ever/rvc-portable --update-install-conf
```

Poi carica i file `dist\RVC-Portable-runtime-windows-py39-cu118.zip.001` e `.002` nella release
`runtime-vX.Y.Z` (GitHub web: «Attach binaries»). Il limite GitHub è 2 GiB per asset: per questo è
diviso in parti. Dopo il caricamento verifica che `install.conf` abbia URL, SHA-256, dimensione e
numero parti corretti.

## 5. Cosa non va mai committato

Il repository deve restare **solo sorgenti**. Non committare:

- `runtime/`, `Modelli/`, `Necessari/`, `Dataset_spot/`, `data/`, `dist/`, `build/`
- `*.apk`, `*.zip`, `*.pth`, `*.index`, `*.onnx`
- `app/release.jks`, `keystore.properties` (chiave di firma: tienila privata)
- `AGENTS.md` (documentazione interna di sviluppo, già ignorata)
- token, password, file `.env`

Se hai già messo per sbaglio un file grosso: `git restore --staged <file>` e aggiungi la regola in
`.gitignore`. Per file grossi da distribuire usa le **Releases**, non il repository.

## 6. RVC locale ONNX: decisione presa

La pipeline ONNX locale sull'app è **disattivata** (`RvcFeatures.LOCAL_ONNX_ENABLED = false`):
richiedeva la conversione `.pth → .onnx` + indice `.fbin` ed era troppo fragile/macchinosa.

Il flusso supportato e testato è **RVC remoto**: il PC usa direttamente i `.pth` con PyTorch/CUDA.
Quindi **non serve aggiungere un tool di conversione**: non ci sono modelli ONNX da produrre.

Se un giorno si vorrà riattivare il locale, allora avrà senso aggiungere anche il convertitore nel
PC e testarlo su un telefono reale; per ora sarebbe solo complessità in più.

## 7. Ottimizzazioni già fatte e prossimi passi

Già fatte:

- Android: RVC locale nascosto, flusso solo remoto; niente modelli ONNX sul telefono.
- PC: `status.json` compatto (heartbeat per il controllo remoto), installer corretto, docs aggiornate.
- Repository Android: solo sorgenti (~27 MB dopo la rimozione degli header PyTorch inutilizzati), modelli/APK/keystore esclusi; CI verde.
- Runtime PC: release completa e installazione da clone pulito verificata.

Prossimi passi possibili (da fare solo se vuoi):

1. **Ridurre l'APK** rimuovendo del tutto le librerie native ONNX (ORA ~33,7 MB → stima ~20 MB);
   richiede una build e un test su telefono reale.
2. Eliminare il codice morto della pipeline ONNX locale (RvcView, modelli, log) dopo il test.
3. Automatizzare la pubblicazione delle release con una GitHub Action (oggi si fa da web UI).
4. Ripulire gli archivi locali `Necessari/` e `Dataset_spot/` (non servono più al flusso normale).

## 8. Comandi di verifica

PC:

```bat
runtime\python.exe -B -m pytest tests -o addopts="" -q
runtime\python.exe -B -m ruff check app tests tools
runtime\python.exe -B -m app --doctor
```

Android:

```bat
set JAVA_HOME=F:\Android\jdk-17.0.12
gradlew.bat :app:testDebugUnitTest
```

Se qualcosa non torna, apri un prompt in `K:\AI\rvc-portable` (PC) o
`K:\AI\Android\rvc-portable-android` (Android) ed esegui un comando alla volta; incolla l'errore
in chat e lo sistemo.
