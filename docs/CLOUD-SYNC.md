# Sincronizzazione cloud (cartella locale o Dropbox OAuth PKCE)

L'app sincronizza **solo il file di configurazione** (`config.json`), mai audio o modelli.

Sono disponibili due modalità, indipendenti:

1. **Percorso locale/cloud/NAS (consigliata)**: scegli un file `config.json` dentro la cartella
   Dropbox, Google Drive, OneDrive o un NAS; con l'hot-reload attivo le modifiche esterne vengono
   rilevate e applicate. È la modalità usata dal **ponte Android** (vedi
   [ANDROID-BRIDGE.md](ANDROID-BRIDGE.md)): nessun token sul PC, basta il client Dropbox desktop.
2. **Dropbox API** (OAuth2 PKCE, nessun server di redirect): carica/scarica il config sul tuo
   account, utile da più macchine o se preferisci non installare il client desktop.

---

## 1. Creare la App Key Dropbox

1. Vai su [dropbox.com/developers/apps](https://www.dropbox.com/developers/apps) → **Create app**.
2. Scegli **Scoped access** → **Full Dropbox** (o App folder, se preferisci).
3. Nel tab **Permissions** abilita:
   - `files.content.read`
   - `files.content.write`
4. Nel tab **Settings**:
   - **Redirect URI**: nessuno (il flusso No-Redirect non lo usa).
   - Copia la **App Key** (è un identificativo pubblico, non un segreto: PKCE non richiede App Secret).
5. Nella UI di RVC Portable → tab **Cloud** → incolla la App Key → **Salva Key**.

> L'errore storico **`Invalid client_id`** significava che la App Key predefinita nel codice non
> era registrata nel tuo account. Ora la chiave è tua e l'errore viene mostrato con questa guida.

## 2. Connettere l'account

1. Premi **Connetti Dropbox**: si apre il browser sull'URL di autorizzazione.
2. Autorizza l'app e copia il **codice** mostrato da Dropbox.
3. Incolla il codice nella finestra dell'app e conferma.

Cosa succede tecnicamente:

```
code_verifier    = 43-128 caratteri casuali
code_challenge   = BASE64URL(SHA256(code_verifier))
GET  https://www.dropbox.com/oauth2/authorize?client_id=…&response_type=code
     &code_challenge=…&code_challenge_method=S256&token_access_type=offline
POST https://api.dropboxapi.com/oauth2/token   (authorization_code + code_verifier)
POST https://api.dropboxapi.com/oauth2/token   (refresh_token, quando scade l'access token)
```

Il **refresh token** viene salvato in `data/state/dropbox.json` con permessi ristretti (0600 su
POSIX). Non viene mai scritto nei log. La App Key resta in `data/config.json`.

## 3. Caricare e scaricare

- **Carica**: salva il config locale (validato) e lo invia a `/NLTools/RVC/config.json`
  (percorso configurabile in `cloud.dropbox.remote_path`).
- **Scarica**: verifica la revisione remota; se il remoto è più recente lo scarica e ricarica la UI.
- **Conflitti**: se il file remoto è cambiato dall'ultima sincronizzazione la UI chiede conferma
  (forza o annulla). Non sovrascrive mai in silenzio.

## 4. Modalità percorso locale (alternativa)

1. Tab **Cloud** → sezione *Sincronizzazione file locale/cloud*.
2. Seleziona il `config.json` nella cartella Dropbox/NAS.
3. Abilita **Hot-reload** (poll ogni 3 s, con debounce).
4. Quando il file cambia, la UI mostra un banner: **Ricarica** applica, **Annulla** mantiene le
   modifiche in corso.

Questa modalità funziona anche senza OAuth e senza rete (basta che la cartella sia sincronizzata
dal client Dropbox/OneDrive).

## 5. Errori e cosa fare

| Codice | Significato | Azione |
|---|---|---|
| `dropbox_not_configured` | App Key assente | incolla la App Key e salva |
| `dropbox_invalid_client` | App Key non valida/non registrata | verifica la chiave nella App Console; nessun redirect URI |
| `dropbox_invalid_code` | codice scaduto o già usato | riavvia *Connetti* e incolla il nuovo codice |
| `dropbox_conflict` | revisione remota diversa | conferma "forza" o scarica prima |
| `network_error` | rete/DNS/proxy | riprova; controlla firewall/proxy |

Timeout 15 s, 2 tentativi con backoff su 429/5xx (rispetta `Retry-After`).

## 6. Sicurezza

- Solo HTTPS verso `dropboxapi.com`/`www.dropbox.com`.
- Nessun App Secret: PKCE è sicuro per client pubblici.
- Token con permessi minimi (`files.content.read/write`), revocabili da Dropbox in qualsiasi momento
  (o con **Disconnetti** nella UI, che rimuove il token locale).
- Il backend ascolta solo su loopback e richiede il token di sessione: nessuna esposizione in rete.
