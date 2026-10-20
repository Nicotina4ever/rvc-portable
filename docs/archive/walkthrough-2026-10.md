# 🎙️ RVC Portable (NL Tools Suite) — Walkthrough & Guida Operativa

Abbiamo completato l'unificazione, il refactoring dell'architettura e l'ottimizzazione del pacchetto.

---

## 🎯 Obiettivi Raggiunti

1. **Risoluzione Bug Configurazione Cloud**:
   - `config_manager.py` ora implementa la lettura degli argomenti da CLI (`--config <path>` o `-c <path>`).
   - È stato introdotto un sistema di **Hot-Reload automatico**: se il file di configurazione remoto o condiviso (Dropbox, NAS o rete) viene modificato, la GUI e il monitor ricaricano i parametri in tempo reale senza dover riavviare l'applicazione.
2. **Nuova GUI Moderna e Professionale**:
   - Realizzata con **CustomTkinter** con tema dark moderno in stile Windows 11.
   - Organizzata in comodi Tab:
     - 📁 **Configurazione**: Selezione cartelle, percorsi modello/indice con slider dinamici per pitch, protezione e index rate.
     - 🎧 **Monitoraggio**: Controllo dello stato del demone audio, avvio/arresto e log live formattato con timestamp.
     - ☁️ **Cloud & Rete**: Supporto per Dropbox OAuth2 PKCE (per sincronizzare i parametri senza chiavi fisse) e gestione dei percorsi cloud remoti.
     - ⚙️ **Avanzate**: Rilevamento hardware dinamico e selezione algoritmo pitch (`rmvpe`, `harvest`, `crepe`, `pm`, `fcpe`).
3. **Internazionalizzazione (Multi-lingua)**:
   - Supporto bilingue integrato **Italiano (IT)** e **English (EN)**, selezionabile direttamente dall'header della GUI.
4. **Architettura Modulare Multi-OS**:
   - Lanciatore unificato Windows: `run.bat`
   - Lanciatore unificato Linux/macOS: `run.sh`
   - Wizard di setup accelerazione: `setup_hardware.bat` / `setup_wizard.py`
5. **Ottimizzazione e Pulizia Runtime**:
   - Disinstallati oltre 250MB di librerie pesanti e inutilizzate per l'inferenza (`gradio`, `FreeSimpleGUI`, `matplotlib`, `pandas`, `tensorboard`, `opencv-python-headless`).
   - Riconfigurato l'ambiente per il corretto funzionamento di PyTorch CUDA (rilevata: **NVIDIA GeForce RTX 4060 Ti**).
   - I vecchi script sparsi sono stati ordinati e archiviati nella cartella `legacy/`.

---

## 🚀 Come Avviare l'Applicazione

### Su Windows
Fai doppio click su:
```bat
run.bat
```
*(Oppure se desideri passare un file cloud specifico da terminale: `run.bat --config "J:\Dropbox\config.json"`)*

### Configurazione Acceleratore Hardware (Opzionale)
Se desideri cambiare backend (es. passare a CPU, DirectML per AMD/Intel, o CUDA):
```bat
setup_hardware.bat
```

### Su Linux / macOS
Da terminale:
```bash
chmod +x run.sh
./run.sh
```
