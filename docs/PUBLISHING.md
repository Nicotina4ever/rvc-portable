# Pubblicare il progetto su GitHub

Questa guida è per chi mantiene il repository. Gli utenti finali trovano invece le
istruzioni in [INSTALL.md](INSTALL.md).

Obiettivo: repository leggero (sorgenti, UI, docs) e **runtime pesante come asset di una
Release**, così chi clona non scarica 5,7 GB ma li ottiene con `setup.bat` al primo avvio.

## 0. Prima di pubblicare

- **Licenza**: aggiungi un file `LICENSE` (es. MIT) se vuoi che il progetto sia riutilizzabile.
  Senza licenza restano validi tutti i diritti riservati. Aggiorna la sezione *Licenza* del README.
- **Segreti**: nel repository non devono esserci token Dropbox né percorsi personali.
  Il controllo automatico è:

  ```bash
  python tools/check_repo.py        # (con il runtime)  oppure: python tools/dev.py check-repo
  ```

  Verifica file obbligatori, cartelle locali (`runtime/`, `Modelli/`, `data/`, `da_eliminare/`,
  `dist/`, `.dev/`), file troppo grandi e pattern di segreti.
- **Dimensione**: il repository deve restare nell'ordine di pochi MB. Il `.gitignore` esclude
  già runtime, modelli, dati, quarantena e archiviazioni.

## 1. Creare il repository e fare il primo push

Crea su GitHub un repository **vuoto** (senza README, licenza o .gitignore), poi:

```bash
cd /percorso/rvc-portable
git branch -M main
git remote add origin https://github.com/Nicotina4ever/rvc-portable.git
git add -A
git commit -m "RVC Portable 3.0.0 — backend locale, UI web, multi-OS"
git push -u origin main
```

Controlla che GitHub non segnali file troppo grandi: se succede, manca una voce nel
`.gitignore` (esegui `tools/check_repo.py` e correggi).

## 2. Costruire l'asset del runtime Windows

Su una macchina Windows con il runtime funzionante (quella di sviluppo):

```bat
runtime\python.exe -B tools\build_runtime_asset.py --repo Nicotina4ever/rvc-portable --update-install-conf
```

Il comando:

1. verifica che il runtime importi torch/rvc-python;
2. crea `dist\RVC-Portable-runtime-windows-py39-cu118.zip` (~3,5 GB);
3. se supera 2 GiB lo divide in parti `.001`, `.002`, ... (limite GitHub per asset)
   e scrive `dist\*.zip.manifest.json` con l'elenco esatto dei file da caricare;
4. aggiorna `install.conf` con URL, SHA-256, dimensione e numero di parti.

Se l'asset è **già stato costruito** e devi solo aggiornare l'URL (es. dopo aver creato il
repository), usa:

```bat
runtime\python.exe -B tools\build_runtime_asset.py --repo Nicotina4ever/rvc-portable --only-update-conf
```

## 3. Creare la Release con il runtime

Su GitHub → *Releases* → *Draft a new release*:

- **Tag**: `runtime-v3.0.0` (deve corrispondere a quello usato dal comando sopra);
- **Titolo**: `Runtime Windows 3.0.0 (Python 3.9.13 + CUDA 11.8)`;
- allega **tutti** i file elencati in `dist\*.zip.manifest.json` (lo `.zip` oppure le parti
  `.001`, `.002`, ... con lo stesso nome base dell'URL in `install.conf`);
- pubblica la release.

Verifica che l'URL in `install.conf` risponda (deve iniziare il download):

```text
https://github.com/Nicotina4ever/rvc-portable/releases/download/runtime-v3.0.0/RVC-Portable-runtime-windows-py39-cu118.zip
```

## 4. Committare la configurazione installer

```bash
git add install.conf
git commit -m "Installer: runtime Windows 3.0.0"
git push
```

> `dist/` è ignorato da git: committa solo `install.conf`. Se vuoi conservare l'elenco
> degli asset come documentazione, copia `dist/*.manifest.json` in `docs/` e committalo.

## 5. Test da zero (importante)

Su una cartella pulita, come farebbe un utente:

```bat
git clone https://github.com/Nicotina4ever/rvc-portable.git "D:\Test-RVC"
cd /d "D:\Test-RVC"
setup.bat
run.bat
```

Verifica: download → hash SHA-256 → estrazione → `--doctor` con esito `OK` → app aperta.
Su macOS/Linux: `./setup.sh` e `./run.sh`.

## 6. CI e release automatiche

- `.github/workflows/ci.yml`: lint, test unitari/integrazione, cataloghi i18n e igiene repository
  su Windows/macOS/Linux a ogni push.
- `.github/workflows/release.yml` (manuale): crea gli archivi **sorgente** per i tre OS.
  Il runtime Windows non viene ricostruito in CI (servirebbe una macchina Windows con GPU e
  ~6 GB di dipendenze): va allegato manualmente come descritto sopra.

Aggiornando il runtime in futuro, cambia `--tag` (es. `runtime-v3.0.1`) e rilancia il comando:
`install.conf` verrà aggiornato con il nuovo hash.

## 7. Note utili

- GitHub limita ogni asset a **2 GiB**: da qui la divisione in parti; `setup.bat` le ricompone.
- Non serve Git LFS: runtime e modelli non sono versionati.
- Se pubblichi anche i modelli vocali, fallo in una release separata e ricorda che i `.pth`
  possono avere licenze proprie: non caricarli senza permesso.
- Per una release "sorgente" pronta da caricare: `python tools/make_release.py --target windows --target macos --target linux`
  (crea `dist/RVC-Portable-3.0.0-*.zip|tar.gz` + `SHA256SUMS`).
