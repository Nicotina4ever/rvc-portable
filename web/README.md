# `web/` — SPA di RVC Portable 3.0

Interfaccia statica, **zero-build**: nessun npm, nessun bundler, nessuna CDN, nessun font esterno.
Servita dal backend FastAPI (`app/api/static.py`):

| URL | Sorgente |
|---|---|
| `/` | `web/index.html` |
| `/css/*` | `web/css/` |
| `/js/*` | `web/js/` |
| `/assets/*` | `web/assets/` |
| `/locales/*` | `locales/` (radice del progetto) |

## Struttura

```
web/
  index.html            layout, sprite SVG inline, dialog, auth screen
  css/
    tokens.css          palette e variabili (tema scuro/chiaro)
    base.css            reset, header/nav/footer, accessibilità, responsive
    components.css      bottoni, card, form, badge, toast, modali
    views.css           stili specifici delle viste
  js/
    app.js              bootstrap: token, i18n, tema, SSE, router, shortcut
    core/
      api.js            client HTTP + envelope errori + endpoint
      data.js           caricamento dati con degrado esplicito
      dom.js            helper DOM e formattazione date/durate
      events.js         trasporto SSE con backoff e Last-Event-ID
      i18n.js           cataloghi it/en, t(), errori tradotti
      router.js         router delle viste (senza hash)
      settings.js       lettura/patch impostazioni
      store.js          stato condiviso con pub/sub
      theme.js          tema dark/light/system
    components/
      fields.js         campi form accessibili (slider, path, switch, select)
      jobboard.js       coda job con progress, cancel, player, log
      modal.js          conferme distruttive e pannelli
      player.js         player audio con waveform canvas e seek
      toast.js          notifiche non bloccanti
      ui.js             card, badge, bottoni, empty state, progress
    views/
      dashboard.js, config.js, monitor.js, models.js,
      cloud.js, advanced.js, setup.js
  assets/
    icon.svg            favicon / icona app
    sprites.svg         sprite SVG standalone (index.html lo incorpora inline)
```

## Regole rispettate

- **CSP del backend**: `script-src 'self'`, nessuno script inline, nessuno stile inline
  (l'unica eccezione in `components.css` è `style-src 'unsafe-inline'` previsto dal backend;
  il frontend non ne ha bisogno: nessun attributo `style=`).
- **Autenticazione**: token letto da `?t=`, salvato in `sessionStorage` e rimosso dalla URL
  con `history.replaceState`; header `Authorization: Bearer` su ogni `/api/*`;
  `EventSource` usa `?t=` e `since`.
- **Degrado**: ogni vista intercetta errori (404/501/503, `engine_unavailable`, stub non
  implementati) e mostra un empty state con messaggio, senza crashare la SPA.
- **i18n**: nessuna stringa UI hardcoded nelle viste; cataloghi `locales/it.json` e
  `locales/en.json` con parità perfetta delle chiavi.
- **Accessibilità**: label associate, `aria-current` sulla navigazione, `aria-live` su
  toast e log, ruoli tab/status, focus visibile, `prefers-reduced-motion`.
- **Responsive**: layout funzionante da 360px a 1440px.

## Sviluppo

Modificare i file e ricaricare la pagina: non serve ricompilare nulla.
Per una verifica statica veloce: `node --check` su ogni `.js` (copiato con estensione `.mjs`).
