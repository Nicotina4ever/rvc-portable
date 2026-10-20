/* RVC Portable — i18n: cataloghi JSON statici (it/en), parità garantita dai test. */

export const SUPPORTED_LANGUAGES = ["it", "en"];
const FALLBACK_LANGUAGE = "it";
const catalogs = new Map();
let language = FALLBACK_LANGUAGE;

function catalog(code) {
  return catalogs.get(code) || {};
}

export async function loadCatalog(code) {
  const normalized = String(code || "").toLowerCase().slice(0, 2);
  if (!SUPPORTED_LANGUAGES.includes(normalized)) return catalog(FALLBACK_LANGUAGE);
  if (catalogs.has(normalized)) return catalogs.get(normalized);
  try {
    const response = await fetch("/locales/" + normalized + ".json", { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    catalogs.set(normalized, data && typeof data === "object" ? data : {});
  } catch (err) {
    console.warn("catalogo lingua non caricato:", normalized, err);
    catalogs.set(normalized, {});
  }
  return catalog(normalized);
}

export async function loadCatalogs() {
  await Promise.all(SUPPORTED_LANGUAGES.map((code) => loadCatalog(code)));
  return catalogs;
}

export function setLanguage(code) {
  const normalized = String(code || "").toLowerCase().slice(0, 2);
  language = SUPPORTED_LANGUAGES.includes(normalized) ? normalized : FALLBACK_LANGUAGE;
  try {
    document.documentElement.lang = language;
  } catch (err) {
    /* ambiente senza document (test) */
  }
  return language;
}

export function getLanguage() {
  return language;
}

export function hasKey(key) {
  return Object.prototype.hasOwnProperty.call(catalog(language), key);
}

export function t(key, params) {
  if (!key) return "";
  const strings = catalog(language);
  const fallback = catalog(FALLBACK_LANGUAGE);
  let text = Object.prototype.hasOwnProperty.call(strings, key) ? strings[key] : fallback[key];
  if (text === undefined || text === null) text = key;
  text = String(text);
  if (params && typeof params === "object") {
    text = text.replace(/\{(\w+)\}/g, (match, name) => {
      const value = params[name];
      return value === undefined || value === null ? match : String(value);
    });
  }
  return text;
}

/** Applica le traduzioni agli elementi statici marcati con data-i18n*. */
export function applyStatic(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.getAttribute("data-i18n");
    if (key) node.textContent = t(key);
  });
  scope.querySelectorAll("[data-i18n-title]").forEach((node) => {
    const key = node.getAttribute("data-i18n-title");
    if (key) node.setAttribute("title", t(key));
  });
  scope.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    const key = node.getAttribute("data-i18n-aria-label");
    if (key) node.setAttribute("aria-label", t(key));
  });
  scope.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    const key = node.getAttribute("data-i18n-placeholder");
    if (key) node.setAttribute("placeholder", t(key));
  });
}

/** Traduzione del codice errore API (fallback: messaggio del server). */
export function errorText(err) {
  const code = err && err.code ? String(err.code) : "";
  const key = "errors." + code;
  if (code && hasKey(key)) return t(key);
  const message = err && err.message ? String(err.message).trim() : "";
  return message || t("errors.generic");
}

/** Dettaglio tecnico aggiuntivo (messaggio server, detail, status HTTP). */
export function errorDetail(err) {
  const parts = [];
  const translated = errorText(err);
  const message = err && err.message ? String(err.message).trim() : "";
  if (message && message !== translated && !translated.startsWith(message) && !message.startsWith(translated)) {
    parts.push(message);
  }
  if (err && err.detail) parts.push(String(err.detail).trim());
  if (err && err.status) parts.push("HTTP " + err.status);
  return parts.filter(Boolean).join(" · ");
}

export function errorFull(err) {
  const main = errorText(err);
  const detail = errorDetail(err);
  return detail ? main + " — " + detail : main;
}
