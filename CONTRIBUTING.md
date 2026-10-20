# Contribuire

Grazie per l'interesse! Questo progetto è un'app **portatile multi-OS** con backend locale:
le modifiche devono restare compatibili con il runtime Python 3.9 (Windows) e 3.10+ (macOS/Linux).

## Preparare l'ambiente di sviluppo

Serve Windows con il runtime del motore (o macOS/Linux con `./setup.sh`):

```bat
:: Windows (dalla cartella del progetto)
runtime\python.exe -B tools\bootstrap.py --dev      :: pytest + ruff in .dev/site-packages
runtime\python.exe -B tools\bootstrap.py --check    :: verifica motore e pesi
```

```bash
# macOS / Linux
./setup.sh
./runtime/bin/python3 -m pip install -r requirements/dev.txt
```

Il repository **non contiene** `runtime/`, i modelli né `data/`: vedi
[docs/INSTALL-WINDOWS.md](docs/INSTALL-WINDOWS.md) e [docs/PUBLISHING.md](docs/PUBLISHING.md).

## Comandi utili

```bash
python tools/dev.py test          # test unitari + integrazione
python tools/dev.py lint          # ruff (app, tests, tools)
python tools/dev.py check-web     # sintassi dei moduli JS (se hai Node)
python tools/dev.py check-repo    # igiene repository (prima del push)
python tools/dev.py i18n          # parità cataloghi IT/EN
python tools/dev.py doctor        # diagnostica ambiente
```

Test reali con GPU (facoltativi, richiedono il runtime e i modelli):

```bash
runtime\python.exe -B tests\e2e\run_real_conversion.py
runtime\python.exe -B tests\e2e\run_api_e2e.py
runtime\python.exe -B tests\e2e\run_android_bridge.py
```

## Regole del progetto

- **Python 3.9 compatibile**: niente `match`, niente `X | Y` nei type hint, niente sintassi 3.10+.
- **Nessuna dipendenza esterna per la UI**: niente npm, CDN, font remoti; solo HTML/CSS/JS e SVG.
- **Nessun segreto nel repository**: token, App Key e percorsi personali restano in `data/`.
- **Torch < 2.6** sul runtime: i checkpoint fairseq non si caricano con `weights_only=True`.
- **Non toccare** `Modelli/` e i file dell'utente in `data/`; la quarantena è locale e ignorata da git.
- Test e lint devono passare; per i cambi UI allega uno screenshot (`python tools/screenshots.py`).

## Flusso di lavoro

1. Apri una issue o descrivi la modifica nella PR.
2. Crea un branch (`feat/...`, `fix/...`).
3. Implementa con test; esegui `python tools/dev.py test` e `python tools/dev.py lint`.
4. Esegui `python tools/dev.py check-repo` per verificare che non finiscano file pesanti/locali.
5. Apri la pull request: la CI esegue lint, test (Windows/macOS/Linux, Python 3.9/3.12),
   validazione i18n e igiene repository.

## Pubblicare una nuova versione

Segui [docs/PUBLISHING.md](docs/PUBLISHING.md): aggiorna `CHANGELOG.md` e la versione in
`app/__init__.py`, ricostruisci l'asset runtime con
`tools/build_runtime_asset.py --repo Nicotina4ever/rvc-portable --update-install-conf` e crea la release GitHub.
