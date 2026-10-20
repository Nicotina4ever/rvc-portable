/* RVC Portable — tema scuro/chiaro/sistema, nessuno stile inline. */
import { state, setState } from "./store.js";

const media = typeof window !== "undefined" && window.matchMedia
  ? window.matchMedia("(prefers-color-scheme: light)")
  : null;

const THEMES = ["dark", "light", "system"];

export function normalizeTheme(theme) {
  return THEMES.includes(theme) ? theme : "dark";
}

export function resolveTheme(theme) {
  const value = normalizeTheme(theme);
  if (value === "system") return media && media.matches ? "light" : "dark";
  return value;
}

export function applyTheme(theme) {
  const normalized = normalizeTheme(theme);
  const resolved = resolveTheme(normalized);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.dataset.themeMode = normalized;
  setState("theme", { theme: normalized, resolvedTheme: resolved });
  return resolved;
}

export function initTheme() {
  if (!media) return;
  const onChange = () => {
    if (state.theme === "system") applyTheme("system");
  };
  if (media.addEventListener) media.addEventListener("change", onChange);
  else if (media.addListener) media.addListener(onChange);
}
