/* RVC Portable — lettura e patch delle impostazioni condivise. */
import { endpoints } from "./api.js";
import { state, setState } from "./store.js";

export function applySettingsSnapshot(snapshot, reason = "settings") {
  if (!snapshot || !snapshot.settings) {
    setState(reason || "settings", { settingsLoaded: true });
    return null;
  }
  setState(reason || "settings", {
    settings: snapshot.settings,
    settingsMeta: {
      warnings: Array.isArray(snapshot.warnings) ? snapshot.warnings : [],
      problems: Array.isArray(snapshot.problems) ? snapshot.problems : [],
      config_path: snapshot.config_path || "",
    },
    settingsLoaded: true,
  });
  return snapshot.settings;
}

export async function loadSettings(reason = "settings") {
  const snapshot = await endpoints.settings();
  applySettingsSnapshot(snapshot, reason);
  return snapshot;
}

export async function patchSettings(patch, reason = "settings") {
  const snapshot = await endpoints.patchSettings(patch);
  applySettingsSnapshot(snapshot, reason);
  return snapshot;
}

export function audioSettings() {
  return (state.settings && state.settings.audio) || {};
}

export function uiSettings() {
  return (state.settings && state.settings.ui) || {};
}

export function engineSettings() {
  return (state.settings && state.settings.engine) || {};
}

export function cloudSettings() {
  return (state.settings && state.settings.cloud) || {};
}
