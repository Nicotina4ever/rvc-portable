/* RVC Portable — caricamento dati dal backend, con degrado esplicito. */
import { endpoints } from "./api.js";
import { state, setState, upsertJob } from "./store.js";

export async function loadHealth() {
  try {
    const health = await endpoints.health();
    setState("health", { health });
    if (health && health.version) setState("version", { version: health.version });
    return health;
  } catch (err) {
    return null;
  }
}

/** Stato motore: prima /api/meta, altrimenti fallback su /api/health. */
export async function loadEngineStatus() {
  try {
    const meta = await endpoints.meta();
    return applyMeta(meta);
  } catch (err) {
    const health = await loadHealth();
    if (health) setState("engine", { health });
    return null;
  }
}

function applyMeta(meta) {
  if (!meta || typeof meta !== "object") return null;
  setState("engine", {
    meta,
    engine: meta.engine && typeof meta.engine === "object" ? meta.engine : state.engine,
    version: meta.version || state.version,
  });
  return meta;
}

/** Snapshot motore normalizzato (meta oppure ripiego su health/settings). */
export function engineSnapshot() {
  const engine = state.engine;
  if (engine && typeof engine.available === "boolean") return engine;
  const health = state.health;
  if (!health) return null;
  const settings = state.settings || {};
  const requested = (settings.engine && settings.engine.device) || "auto";
  return {
    available: Boolean(health.engine_available),
    code: health.engine_available ? "" : "engine_unavailable",
    message: "",
    device: requested,
    requested_device: requested,
    model_path: (settings.audio && settings.audio.model_path) || "",
    index_path: (settings.audio && settings.audio.index_path) || "",
    model_version: (settings.audio && settings.audio.model_version) || "v2",
    loaded: false,
    warm: false,
    busy: false,
    extra: {},
    source: "health",
  };
}

export async function loadJobs(options = {}) {
  const silent = Boolean(options.silent);
  try {
    const data = await endpoints.jobs(options.limit || 50);
    setState("jobs", {
      jobs: Array.isArray(data.jobs) ? data.jobs : [],
      stats: data.stats || {},
      current: data.current || null,
      jobsLoaded: true,
      jobsError: null,
    });
    return data;
  } catch (err) {
    if (!silent) setState("jobs", { jobsLoaded: true, jobsError: err });
    return null;
  }
}

export function applyJob(job) {
  if (!job || !job.id) return;
  upsertJob(job);
  setState("jobs");
}

export async function loadMonitor(options = {}) {
  try {
    const data = await endpoints.monitor();
    setState("monitor", {
      monitor: {
        running: Boolean(data && data.running),
        dir: (data && data.dir) || "",
        mode: (data && data.mode) || "",
        queued: Number((data && data.queued) || 0),
        processed_session: Number((data && data.processed_session) || 0),
      },
      monitorLoaded: true,
      monitorError: null,
    });
    return data;
  } catch (err) {
    if (!options.silent) setState("monitor", { monitorLoaded: true, monitorError: err });
    return null;
  }
}

export async function loadHardware(options = {}) {
  try {
    const data = await endpoints.hardware();
    setState("hardware", { hardware: data, hardwareError: null });
    return data;
  } catch (err) {
    setState("hardware", { hardwareError: err });
    return null;
  }
}

export async function loadModels(options = {}) {
  const rescan = Boolean(options.rescan);
  try {
    const data = rescan ? await endpoints.modelsScan() : await endpoints.models();
    setState("models", {
      models: {
        roots: Array.isArray(data.roots) ? data.roots : [],
        models: Array.isArray(data.models) ? data.models : [],
        warnings: Array.isArray(data.warnings) ? data.warnings : [],
      },
      modelsError: null,
    });
    return data;
  } catch (err) {
    setState("models", { modelsError: err, models: state.models });
    return null;
  }
}

export async function loadCloud() {
  try {
    const data = await endpoints.cloudStatus();
    setState("cloud", { cloud: data, cloudError: null });
    return data;
  } catch (err) {
    setState("cloud", { cloudError: err });
    return null;
  }
}

export async function loadDiagnostics(force = false) {
  try {
    const data = await endpoints.diagnostics(force);
    setState("diagnostics", { diagnostics: data, diagnosticsError: null });
    return data;
  } catch (err) {
    setState("diagnostics", { diagnosticsError: err });
    return null;
  }
}

/** Ricarica in blocco i dati di sfondo usati da header/footer/dashboard. */
export async function refreshCoreData() {
  await Promise.allSettled([loadHealth(), loadEngineStatus(), loadJobs({ silent: true }), loadMonitor({ silent: true })]);
}
