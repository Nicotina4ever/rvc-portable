# Creare un file indice con Replay

L'indice (`.index`) migliora la somiglianza timbrica della voce convertita. È opzionale ma
consigliato. Replay crea il modello `.pth` in una cartella `model`; in un'altra posizione
(su Windows: `train`) crea le cartelle con i dettagli del modello, tra cui `experiment`
(quella che ci interessa).

Esegui dalla radice del progetto (dopo `setup.bat` / `./setup.sh`):

```bat
runtime\python.exe -m rvc_python index -mp path\to\model.pth -ld path\to\experiment -o path\to\output.index
```

| Opzione | Significato |
|---|---|
| `-mp` | percorso del modello `.pth` generato da Replay |
| `-ld` | percorso della cartella `experiment` (log di Replay) |
| `-o` | percorso dove salvare il file `.index` |

Il comando estrae le feature dal modello e costruisce l'indice.

## Esempio (versione portatile)

Supponendo `C:\Replay\model` e `C:\Replay\train\experiment`:

```bat
runtime\python.exe -m rvc_python index -mp C:\Replay\model\model.pth -ld C:\Replay\train\experiment -o "Modelli\mio-modello.index"
```

Poi indicizza il file dalla tab **Configurazione → Index** (o lascia vuoto per non usarlo).

> Se il modello clonato viene creato direttamente da RVC (non da Replay), l'indice viene
> generato automaticamente e questo passaggio non serve. Nella 3.0 il suffisso `trained_*`
> viene riconosciuto come alias di `added_*` (nessuna rinomina manuale necessaria).
