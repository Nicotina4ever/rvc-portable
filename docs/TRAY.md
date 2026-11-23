# System tray (Windows)

Quando l'app viene avviata in modalità grafica (non `--headless` e non `--browser none`)
compare l'icona **RVC Portable** nella system tray di Windows. La finestra può essere chiusa:
l'app resta attiva e continua a lavorare (monitor, coda, training).

## Menu dell'icona

| Voce | Azione |
|---|---|
| **Mostra RVC Portable** | riapre l'interfaccia nel browser/app-mode |
| **Avvia monitoraggio** | avvia il watcher sulla cartella input configurata |
| **Ferma monitoraggio** | ferma il watcher |
| **Ferma monitoraggio e motore** | ferma il watcher e scarica il modello dalla VRAM |
| **Scarica motore** | scarica solo il modello (utile prima di usare altra GPU) |
| **Apri cartella Modelli** | apre `Modelli/` in Esplora file |
| **Apri cartella log** | apre `data/logs/` |
| **Esci (chiudi applicazione)** | spegne l'app e rimuove l'icona |

Il pallino/menu mostra lo stato: monitor attivo/fermo e motore pronto/non pronto.

## Disattivare la tray

```bat
run.bat --no-tray
```

Oppure in `run-console.bat` aggiungi `--no-tray`. Con `--headless` la tray non viene creata.

## Note

- La tray usa solo API locali con token: nessuna porta in più, nessun accesso di rete.
- Se chiudi la finestra, l'app resta attiva nella tray e l'uscita automatica per inattività è
  disabilitata (l'uscita esplicita è dal menu).
- L'icona è `web/assets/icon.ico`, inclusa nell'archivio di release.
- Su macOS/Linux la tray non è attiva: il comportamento resta quello classico.
