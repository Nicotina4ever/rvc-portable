/* RVC Portable — stato applicativo condiviso e pub/sub minimale. */

export const state = {
  booted: false,
  token: "",
  lang: "it",
  theme: "dark",
  resolvedTheme: "dark",
  version: "3.0.0",
  settingsLoaded: false,
  settings: null,
  settingsMeta: { warnings: [], problems: [], config_path: "" },
  health: null,
  meta: null,
  engine: null,
  jobs: [],
  jobsLoaded: false,
  jobsError: null,
  stats: {},
  current: null,
  monitor: { running: false, dir: "", mode: "", queued: 0, processed_session: 0 },
  monitorLoaded: false,
  monitorError: null,
  hardware: null,
  hardwareError: null,
  models: null,
  modelsError: null,
  diagnostics: null,
  diagnosticsError: null,
  cloud: null,
  cloudError: null,
  logs: [],
  jobLogs: Object.create(null),
  lastJobLog: null,
  externalConfig: null,
  sseStatus: "connecting",
  fatal: null,
  setupDismissed: false,
};

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function emit(reason) {
  const snapshot = Array.from(listeners);
  for (const listener of snapshot) {
    try {
      listener(reason || "state");
    } catch (err) {
      /* un listener rotto non deve fermare la UI */
      console.error("store listener error", err);
    }
  }
}

export function setState(reason, patch) {
  if (patch && typeof patch === "object") Object.assign(state, patch);
  emit(reason || "state");
}

export function getAudio() {
  return (state.settings && state.settings.audio) || null;
}

export function getUI() {
  return (state.settings && state.settings.ui) || null;
}

export function getMonitorSettings() {
  return (state.settings && state.settings.monitor) || null;
}

export function pushLog(entry) {
  const item = Object.assign({ ts: Date.now() / 1000, level: "info", source: "app", message: "" }, entry || {});
  state.logs.push(item);
  if (state.logs.length > 2000) state.logs.splice(0, state.logs.length - 2000);
}

export function pushJobLog(jobId, message) {
  if (!jobId) return;
  const list = state.jobLogs[jobId] || (state.jobLogs[jobId] = []);
  list.push({ message: String(message || ""), ts: Date.now() / 1000 });
  if (list.length > 200) list.splice(0, list.length - 200);
  state.lastJobLog = { job_id: jobId, message: String(message || "") };
}

export function activeJobCount() {
  return state.jobs.filter((job) => job.state === "queued" || job.state === "running").length;
}

export function recomputeStats() {
  const stats = { queued: 0, running: 0, done: 0, failed: 0, canceled: 0, total: state.jobs.length };
  for (const job of state.jobs) {
    if (stats[job.state] !== undefined) stats[job.state] += 1;
  }
  stats.pending = stats.queued + stats.running;
  state.stats = stats;
  return stats;
}

export function upsertJob(job) {
  if (!job || !job.id) return;
  const index = state.jobs.findIndex((item) => item.id === job.id);
  if (index >= 0) state.jobs[index] = job;
  else state.jobs.unshift(job);
  recomputeStats();
}

export function removeJobFromState(jobId) {
  const index = state.jobs.findIndex((job) => job.id === jobId);
  if (index >= 0) state.jobs.splice(index, 1);
  recomputeStats();
}

export function needsSetup() {
  const audio = getAudio();
  if (!audio) return false;
  if (state.setupDismissed) return false;
  return !audio.model_path || !audio.input_dir;
}
