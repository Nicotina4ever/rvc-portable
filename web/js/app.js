/* RVC Portable — bootstrap della SPA: sessione, i18n, tema, SSE, router. */
import { h, div, span, icon, clear, basename, isTypingTarget, isInteractiveTarget, qsa } from "./core/dom.js";
import {
  SUPPORTED_LANGUAGES,
  applyStatic,
  getLanguage,
  loadCatalogs,
  setLanguage as setLanguageCode,
  t,
  errorFull,
} from "./core/i18n.js";
import {
  api,
  endpoints,
  captureTokenFromUrl,
  getToken,
  setToken,
  onUnauthorized,
} from "./core/api.js";
import { state, subscribe, setState, pushLog, pushJobLog } from "./core/store.js";
import { applySettingsSnapshot, loadSettings, patchSettings, uiSettings } from "./core/settings.js";
import { loadHealth, loadEngineStatus, loadJobs, loadMonitor, loadHardware, applyJob, engineSnapshot } from "./core/data.js";
import { applyTheme, initTheme } from "./core/theme.js";
import { connectEvents, disconnectEvents, seedHistory, noteServerLastId, getLastEventId } from "./core/events.js";
import { initToasts, toast } from "./components/toast.js";
import { initModal, panelModal } from "./components/modal.js";
import { btn, emptyState } from "./components/ui.js";
import { initRouter, show as showView, refreshCurrentView, currentViewId, currentView, VIEW_IDS } from "./core/router.js";

const ALLOWED_VIEWS = ["dashboard", "config", "monitor", "models", "cloud", "advanced"];
const LANG_KEY = "rvc.lang";

const refs = {};

function cacheRefs() {
  refs.viewRoot = document.getElementById("view-root");
  refs.nav = document.getElementById("app-nav");
  refs.langSelect = document.getElementById("lang-select");
  refs.themeToggle = document.getElementById("theme-toggle");
  refs.helpButton = document.getElementById("help-button");
  refs.enginePill = document.getElementById("engine-pill");
  refs.enginePillText = document.getElementById("engine-pill-text");
  refs.footerDevice = document.getElementById("footer-device");
  refs.footerJobs = document.getElementById("footer-jobs");
  refs.footerVersion = document.getElementById("footer-version");
  refs.footerSse = document.getElementById("footer-sse");
  refs.footerSseText = document.getElementById("footer-sse-text");
  refs.authScreen = document.getElementById("auth-screen");
  refs.authForm = document.getElementById("auth-form");
  refs.authToken = document.getElementById("auth-token");
  refs.authError = document.getElementById("auth-error");
  refs.toasts = document.getElementById("toast-root");
  refs.modal = document.getElementById("app-modal");
  refs.shell = document.getElementById("app-shell");
}

let sseWasOffline = false;
let lastPersistTimer = null;

/* ------------------------------------------------------------------ sessione */

function showAuth(message) {
  disconnectEvents();
  document.body.dataset.auth = "required";
  if (refs.authScreen) refs.authScreen.hidden = false;
  if (refs.authError) {
    refs.authError.hidden = !message;
    refs.authError.textContent = message || "";
  }
  if (refs.authToken) {
    try {
      refs.authToken.focus({ preventScroll: true });
    } catch (err) {
      /* focus non disponibile */
    }
  }
}

function hideAuth() {
  document.body.dataset.auth = "ok";
  if (refs.authScreen) refs.authScreen.hidden = true;
}

function bindAuthForm() {
  if (!refs.authForm) return;
  refs.authForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = refs.authToken ? refs.authToken.value.trim() : "";
    if (!value) return;
    setToken(value);
    window.location.reload();
  });
}

/* ------------------------------------------------------------------- i18n */

async function setLanguage(code) {
  const normalized = SUPPORTED_LANGUAGES.includes(String(code).slice(0, 2)) ? String(code).slice(0, 2) : "it";
  try {
    await patchSettings({ ui: { language: normalized } });
  } catch (err) {
    console.warn("impossibile salvare la lingua", err);
  }
  setLanguageCode(normalized);
  try {
    sessionStorage.setItem(LANG_KEY, normalized);
  } catch (err) {
    /* storage non disponibile */
  }
  if (refs.langSelect) refs.langSelect.value = normalized;
  applyStatic(document);
  renderChrome();
  await refreshCurrentView();
}

function initialLanguage() {
  let stored = "";
  try {
    stored = sessionStorage.getItem(LANG_KEY) || "";
  } catch (err) {
    stored = "";
  }
  return SUPPORTED_LANGUAGES.includes(stored) ? stored : "it";
}

/* ------------------------------------------------------------------- tema */

function toggleTheme() {
  const next = state.resolvedTheme === "dark" ? "light" : "dark";
  applyTheme(next);
  try {
    sessionStorage.setItem("rvc.theme", next);
  } catch (err) {
    /* storage non disponibile */
  }
  renderChrome();
  patchSettings({ ui: { theme: next } }).catch((err) => console.warn("tema non salvato", err));
}

/* --------------------------------------------------------------- help modal */

function openHelp() {
  const shortcuts = [
    [t("help.keySpace"), t("help.shortcutSpace")],
    [t("help.keySave"), t("help.shortcutSave")],
    [t("help.keyHelp"), t("help.shortcutHelp")],
    [t("help.keyEsc"), t("help.shortcutEsc")],
  ];
  const list = div("shortcut-list");
  for (const [key, description] of shortcuts) {
    list.appendChild(div("shortcut-row", h("kbd", { class: "kbd", text: key }), h("span", { class: "shortcut-desc", text: description })));
  }
  const meta = state.meta || {};
  const content = div(
    "help-content",
    h("h3", { class: "help-heading", text: t("help.shortcuts") }),
    list,
    h("h3", { class: "help-heading", text: t("help.aboutTitle") }),
    h("p", { class: "help-text", text: t("help.aboutText") }),
    h("p", { class: "help-version", text: t("advanced.version") + ": " + (meta.version || state.version || "3.0.0") })
  );
  panelModal({ title: t("help.title"), content, okLabel: t("help.close") });
}

/* ------------------------------------------------------------------ chrome */

function renderEnginePill() {
  if (!refs.enginePill) return;
  const engine = engineSnapshot();
  let kind = "unknown";
  let text = t("engine.unknown");
  let device = "";
  if (engine) {
    device = engine.device || engine.requested_device || "";
    if (engine.available) {
      kind = "ok";
      text = engine.busy ? t("engine.busy") : t("engine.available");
    } else {
      kind = "bad";
      text = t("engine.unavailable");
    }
  } else if (state.settings && state.settings.engine && state.settings.engine.device) {
    device = state.settings.engine.device;
  }
  refs.enginePill.dataset.state = kind;
  if (refs.enginePillText) refs.enginePillText.textContent = text;
  const title = device ? t("footer.device", { device }) : t("header.engineLabel");
  refs.enginePill.title = title;
  refs.enginePill.setAttribute("aria-label", t("header.engineLabel") + ": " + text + (device ? " — " + title : ""));
}

function renderSseStatus() {
  if (!refs.footerSse) return;
  const status = state.sseStatus || "connecting";
  const labels = { connected: "sse.connected", connecting: "sse.connecting", offline: "sse.offline" };
  refs.footerSse.dataset.status = status;
  if (refs.footerSseText) refs.footerSseText.textContent = t(labels[status] || "sse.offline");
}

function renderChrome() {
  renderEnginePill();
  renderSseStatus();
  if (refs.langSelect && refs.langSelect.value !== getLanguage()) refs.langSelect.value = getLanguage();
  if (refs.themeToggle) {
    clear(refs.themeToggle);
    refs.themeToggle.appendChild(icon(state.resolvedTheme === "dark" ? "sun" : "moon"));
    refs.themeToggle.setAttribute("aria-label", t("header.toggleTheme"));
    refs.themeToggle.title = t("header.theme") + ": " + (state.resolvedTheme === "dark" ? t("advanced.themeDark") : t("advanced.themeLight"));
  }
  const engine = engineSnapshot();
  const device = (engine && (engine.device || engine.requested_device)) || (state.settings && state.settings.engine && state.settings.engine.device) || "—";
  if (refs.footerDevice) refs.footerDevice.textContent = t("footer.device", { device });
  const active = state.jobs.filter((job) => job.state === "queued" || job.state === "running").length;
  if (refs.footerJobs) refs.footerJobs.textContent = t("footer.activeJobs", { count: active });
  if (refs.footerVersion) refs.footerVersion.textContent = t("footer.version", { version: state.version || "3.0.0" });
  renderNavActive(currentViewId());
}

function renderNavActive(viewId) {
  if (!refs.nav) return;
  qsa("[data-view]", refs.nav).forEach((button) => {
    const active = button.dataset.view === viewId;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

/* --------------------------------------------------------------- navigation */

async function navigate(view, options, config = {}) {
  const target = VIEW_IDS.includes(view) ? view : "dashboard";
  await showView(target, options);
  renderNavActive(target);
  if (config.persist !== false && target !== "setup" && ALLOWED_VIEWS.includes(target)) {
    if (lastPersistTimer) clearTimeout(lastPersistTimer);
    lastPersistTimer = setTimeout(() => {
      lastPersistTimer = null;
      patchSettings({ ui: { last_view: target } }).catch(() => null);
    }, 350);
  }
}

/* -------------------------------------------------------------- SSE events */

function handleEvent(type, data, replayed) {
  if (!data || typeof data !== "object") return;
  switch (type) {
    case "hello": {
      noteServerLastId(data.last_event_id);
      if (data.token && !getToken()) setToken(data.token);
      if (data.version) setState("version", { version: data.version });
      if (data.engine) setState("engine", { engine: data.engine });
      break;
    }
    case "log": {
      pushLog({
        ts: data.ts,
        level: data.level || "info",
        source: data.source || "app",
        message: data.message || "",
      });
      setState("log");
      break;
    }
    case "job": {
      applyJob(data);
      break;
    }
    case "job_log": {
      if (data.job_id) {
        pushJobLog(data.job_id, data.message);
        const job = state.jobs.find((item) => item.id === data.job_id);
        const prefix = job ? job.basename || basename(job.input_path) : data.job_id.slice(0, 8);
        pushLog({ ts: data.ts, level: "info", source: "job", message: prefix + ": " + (data.message || "") });
        setState("job-log");
        setState("log");
      }
      break;
    }
    case "monitor": {
      setState("monitor", {
        monitor: {
          running: Boolean(data.running),
          dir: data.dir || "",
          mode: data.mode || "",
          queued: Number(data.queued || 0),
          processed_session: Number(data.processed_session || 0),
        },
        monitorLoaded: true,
        monitorError: null,
      });
      break;
    }
    case "config": {
      if (data.source === "api" || data.source === "import") break;
      setState("config-external", { externalConfig: data });
      if (!replayed) toast.info(t("config.externalTitle"));
      break;
    }
    case "engine": {
      setState("engine", { engine: data });
      break;
    }
    case "toast": {
      if (replayed) break;
      const key = data.message_key;
      if (key) {
        const message = t(key, data.params || {});
        toast.show({ level: data.level || "info", message });
      } else if (data.message) {
        toast.show({ level: data.level || "info", message: String(data.message) });
      }
      break;
    }
    default:
      break;
  }
}

async function startEvents() {
  const history = await seedHistory();
  for (const event of history) {
    try {
      handleEvent(event.type, event.data, true);
    } catch (err) {
      console.warn("evento storico non applicato", err);
    }
  }
  connectEvents({
    onEvent: (type, data) => handleEvent(type, data, false),
    onStatus: (status) => {
      if (status === "connected") {
        const wasOffline = sseWasOffline;
        sseWasOffline = false;
        setState("sse", { sseStatus: "connected" });
        if (wasOffline) refreshCore();
      } else {
        sseWasOffline = true;
        setState("sse", { sseStatus: status });
      }
    },
  });
}

async function refreshCore() {
  await Promise.allSettled([
    loadHealth(),
    loadEngineStatus(),
    loadJobs({ silent: true }),
    loadMonitor({ silent: true }),
  ]);
}

/* ------------------------------------------------------------- shortcuts */

async function toggleMonitorShortcut() {
  try {
    if (state.monitor && state.monitor.running) {
      await endpoints.monitorStop();
      toast.success(t("monitor.stopOk"));
    } else {
      const dir = (state.settings && state.settings.audio && state.settings.audio.input_dir) || "";
      if (!dir) {
        toast.warning(t("monitor.dirRequired"));
        return;
      }
      await endpoints.monitorStart({ dir });
      toast.success(t("monitor.startOk"));
    }
    await loadMonitor({ silent: true });
  } catch (err) {
    toast.show({ level: "error", message: t("monitor.unavailable"), detail: errorFull(err) });
  }
}

function bindShortcuts() {
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    if (event.key === "Escape") return; /* gestito dal dialog nativo */
    if (isTypingTarget(event.target)) return;
    if (event.key === " " && !event.ctrlKey && !event.metaKey && !event.altKey) {
      if (isInteractiveTarget(event.target)) return;
      event.preventDefault();
      toggleMonitorShortcut();
      return;
    }
    if ((event.key === "s" || event.key === "S") && !event.ctrlKey && !event.metaKey && !event.altKey) {
      if (isInteractiveTarget(event.target)) return;
      const viewId = currentViewId();
      if (viewId === "config") {
        event.preventDefault();
        const view = currentView();
        if (view && typeof view.onShortcut === "function") view.onShortcut("save");
      }
      return;
    }
    if (event.key === "?" || (event.key === "/" && event.shiftKey)) {
      if (isInteractiveTarget(event.target)) return;
      event.preventDefault();
      openHelp();
    }
  });
}

/* ------------------------------------------------------------------ static */

function bindStaticControls() {
  if (refs.langSelect) {
    refs.langSelect.value = getLanguage();
    refs.langSelect.addEventListener("change", () => setLanguage(refs.langSelect.value));
  }
  if (refs.themeToggle) refs.themeToggle.addEventListener("click", toggleTheme);
  if (refs.helpButton) refs.helpButton.addEventListener("click", openHelp);
  if (refs.enginePill) refs.enginePill.addEventListener("click", () => navigate("advanced"));
  if (refs.nav) {
    qsa("[data-view]", refs.nav).forEach((button) => {
      button.addEventListener("click", () => navigate(button.dataset.view));
    });
  }
  if (refs.footerSse) {
    refs.footerSse.title = t("sse.connected");
  }
}

/* -------------------------------------------------------------- polling */

function startPolling() {
  setInterval(() => {
    if (document.hidden) return;
    if (!getToken()) return;
    if (state.sseStatus !== "connected") {
      refreshCore();
      return;
    }
    if (state.stats && state.stats.pending > 0) loadJobs({ silent: true });
    if (state.monitor && state.monitor.running) loadMonitor({ silent: true });
  }, 4000);
}

/* ------------------------------------------------------------------- boot */

async function boot() {
  cacheRefs();
  captureTokenFromUrl();

  initTheme();
  const storedTheme = (() => {
    try {
      return sessionStorage.getItem("rvc.theme") || "dark";
    } catch (err) {
      return "dark";
    }
  })();
  applyTheme(storedTheme);
  initToasts(refs.toasts);
  initModal(refs.modal);
  bindAuthForm();
  onUnauthorized(() => showAuth(t("app.authInvalid")));

  await loadCatalogs();
  const lang = initialLanguage();
  setLanguageCode(lang);
  applyStatic(document);
  bindStaticControls();
  subscribe((reason) => {
    if (reason === "settings" || reason === "engine" || reason === "health" || reason === "jobs" || reason === "sse" || reason === "theme" || reason === "version") {
      renderChrome();
    }
  });
  renderChrome();

  if (refs.authScreen) refs.authScreen.hidden = true;

  if (!getToken()) {
    showAuth(t("app.authText"));
    return;
  }
  hideAuth();

  try {
    await loadSettings();
  } catch (err) {
    if (err && err.code === "unauthorized") {
      showAuth(t("app.authInvalid"));
      return;
    }
    toast.show({ level: "error", message: t("app.serverOffline"), detail: errorFull(err) });
  }

  const ui = uiSettings();
  const settingsLang = SUPPORTED_LANGUAGES.includes(String(ui.language || "").slice(0, 2)) ? String(ui.language).slice(0, 2) : getLanguage();
  if (settingsLang !== getLanguage()) {
    setLanguageCode(settingsLang);
    applyStatic(document);
  }
  applyTheme(ui.theme || storedTheme);
  try {
    sessionStorage.setItem("rvc.theme", state.theme);
  } catch (err) {
    /* storage non disponibile */
  }
  try {
    state.setupDismissed = sessionStorage.getItem("rvc.setupDismissed") === "1";
  } catch (err) {
    state.setupDismissed = false;
  }
  renderChrome();

  initRouter({
    root: refs.viewRoot,
    context: {
      navigate,
      setLanguage,
      applyTheme,
    },
    onViewChange: (viewId) => renderNavActive(viewId),
  });

  /* prima vista */
  let initial = "dashboard";
  const lastView = ALLOWED_VIEWS.includes(ui.last_view) ? ui.last_view : "dashboard";
  const audio = (state.settings && state.settings.audio) || {};
  if (!state.setupDismissed && (!audio.model_path || !audio.input_dir)) initial = "setup";
  else initial = lastView;
  await navigate(initial, {}, { persist: false });

  /* dati di sfondo + SSE */
  refreshCore();
  await startEvents();
  startPolling();
  bindShortcuts();
}

boot().catch((err) => {
  console.error("errore di avvio SPA", err);
  const root = document.getElementById("view-root");
  if (root) {
    clear(root);
    root.appendChild(
      emptyState({
        iconName: "alert",
        title: t("app.fatalTitle"),
        text: errorFull(err),
        actions: [
          btn(t("app.reload"), {
            variant: "primary",
            iconName: "refresh",
            onClick: () => window.location.reload(),
          }),
        ],
      })
    );
  }
});

/* riferimento per scorciatoie/strumenti esterni (solo lettura) */
window.__rvc = { state, api, getLastEventId };
