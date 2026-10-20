/* RVC Portable — client HTTP: token di sessione, envelope errori, endpoint API. */

const TOKEN_KEY = "rvc.token";
let token = "";
try {
  token = sessionStorage.getItem(TOKEN_KEY) || "";
} catch (err) {
  token = "";
}
let unauthorizedHandler = null;

export class ApiError extends Error {
  constructor(code, message, status, params, detail) {
    super(message || code || "error");
    this.name = "ApiError";
    this.code = code || "internal_error";
    this.status = status || 0;
    this.params = params || {};
    this.detail = detail || "";
  }
}

export function getToken() {
  return token;
}

export function setToken(value, persist = true) {
  token = String(value || "");
  try {
    if (persist && token) sessionStorage.setItem(TOKEN_KEY, token);
    else if (!token) sessionStorage.removeItem(TOKEN_KEY);
  } catch (err) {
    /* storage non disponibile: il token resta in memoria */
  }
  return token;
}

/** Legge ?t= dalla URL, lo salva e ripulisce la barra indirizzi. */
export function captureTokenFromUrl() {
  let found = false;
  try {
    const url = new URL(window.location.href);
    const candidate = url.searchParams.get("t");
    if (candidate) {
      setToken(candidate);
      url.searchParams.delete("t");
      const query = url.searchParams.toString();
      const clean = url.pathname + (query ? "?" + query : "") + url.hash;
      window.history.replaceState(null, "", clean);
      found = true;
    }
  } catch (err) {
    console.warn("impossibile leggere il token dalla URL", err);
  }
  return found;
}

export function onUnauthorized(handler) {
  unauthorizedHandler = typeof handler === "function" ? handler : null;
}

function notifyUnauthorized() {
  if (unauthorizedHandler) {
    try {
      unauthorizedHandler();
    } catch (err) {
      console.error(err);
    }
  }
}

async function parseError(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch (err) {
    payload = null;
  }
  const envelope = payload && payload.error && typeof payload.error === "object" ? payload.error : null;
  if (envelope) {
    return new ApiError(
      envelope.code || "http_error",
      envelope.message || "",
      response.status,
      envelope.params || {},
      envelope.detail || ""
    );
  }
  return new ApiError(
    response.status === 401 ? "unauthorized" : "http_error",
    "HTTP " + response.status + " " + (response.statusText || ""),
    response.status,
    {},
    ""
  );
}

/**
 * Richiesta generica. `json` serializza il corpo; `raw` restituisce la Response.
 * timeoutMs: per i dialoghi nativi serve un timeout lungo.
 */
export async function request(method, path, options = {}) {
  const { json, body, headers, timeoutMs = 20000, raw = false } = options;
  const finalHeaders = Object.assign({ Accept: "application/json" }, headers || {});
  const init = { method, headers: finalHeaders, cache: "no-store" };
  if (json !== undefined) {
    finalHeaders["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (body !== undefined) {
    init.body = body;
  }
  if (token) finalHeaders.Authorization = "Bearer " + token;

  let timer = null;
  let controller = null;
  if (timeoutMs && typeof AbortController !== "undefined") {
    controller = new AbortController();
    init.signal = controller.signal;
    timer = setTimeout(() => controller.abort(), timeoutMs);
  }

  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new ApiError("network_error", "Timeout della richiesta", 0, { path });
    }
    throw new ApiError("network_error", "Connessione al backend non riuscita", 0, { path });
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (response.status === 401) notifyUnauthorized();
  if (!response.ok) throw await parseError(response);
  if (raw) return response;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch (err) {
      throw new ApiError("internal_error", "Risposta JSON non valida", response.status);
    }
  }
  return response.text();
}

export const api = {
  get: (path, options) => request("GET", path, options),
  post: (path, json, options) => request("POST", path, Object.assign({}, options, { json })),
  put: (path, json, options) => request("PUT", path, Object.assign({}, options, { json })),
  patch: (path, json, options) => request("PATCH", path, Object.assign({}, options, { json })),
  del: (path, options) => request("DELETE", path, options),
  blob: async (path, options) => {
    const response = await request("GET", path, Object.assign({}, options, { raw: true }));
    return response.blob();
  },
};

/* ------------------------------------------------------------------ endpoint */

export const endpoints = {
  health: () => api.get("/api/health", { timeoutMs: 6000 }),
  meta: () => api.get("/api/meta"),
  settings: () => api.get("/api/settings"),
  putSettings: (settings) => api.put("/api/settings", { settings }),
  patchSettings: (patch) => api.patch("/api/settings", { patch }),
  exportSettings: () => api.blob("/api/settings/export"),
  importSettings: (settings) => api.post("/api/settings/import", { settings }),
  reveal: (target) => api.post("/api/settings/reveal", { target }),
  jobs: (limit = 50) => api.get("/api/jobs?limit=" + encodeURIComponent(limit)),
  enqueueJob: (payload) => api.post("/api/jobs", payload),
  cancelJob: (id) => api.post("/api/jobs/" + encodeURIComponent(id) + "/cancel"),
  deleteJob: (id) => api.del("/api/jobs/" + encodeURIComponent(id)),
  clearJobs: () => api.post("/api/jobs/clear"),
  waveform: (id, side = "output", buckets = 600) =>
    api.get(
      "/api/jobs/" +
        encodeURIComponent(id) +
        "/waveform?side=" +
        encodeURIComponent(side) +
        "&buckets=" +
        encodeURIComponent(buckets)
    ),
  audioUrl: (id, side = "output") =>
    "/api/jobs/" +
    encodeURIComponent(id) +
    "/audio/" +
    encodeURIComponent(side) +
    (token ? "?t=" + encodeURIComponent(token) : ""),
  monitor: () => api.get("/api/monitor"),
  monitorStart: (payload) => api.post("/api/monitor/start", payload || {}),
  monitorStop: () => api.post("/api/monitor/stop", {}),
  monitorProcessExisting: (payload) => api.post("/api/monitor/process-existing", payload || {}),
  models: () => api.get("/api/models"),
  modelsScan: (roots) => api.post("/api/models/scan", roots ? { roots } : {}),
  modelsProbe: (paths) => api.post("/api/models/probe", { paths }),
  hardware: () => api.get("/api/hardware"),
  diagnostics: (force = false) => api.get("/api/system/diagnostics?force=" + (force ? "true" : "false")),
  shutdown: () => api.post("/api/system/shutdown", {}, { timeoutMs: 5000 }),
  cloudStatus: () => api.get("/api/cloud/dropbox"),
  cloudKey: (appKey) => api.put("/api/cloud/dropbox/key", { app_key: appKey }),
  cloudAuthorize: () => api.post("/api/cloud/dropbox/authorize", {}),
  cloudComplete: (code) => api.post("/api/cloud/dropbox/complete", { code }),
  cloudUpload: (force) => api.post("/api/cloud/dropbox/upload", { force: Boolean(force) }),
  cloudDownload: (force) => api.post("/api/cloud/dropbox/download", { force: Boolean(force) }),
  cloudDisconnect: () => api.del("/api/cloud/dropbox"),
  androidStatus: () => api.get("/api/android"),
  androidDetect: () => api.post("/api/android/detect", {}),
  androidPreset: (sharedDir) => api.post("/api/android/preset", { shared_dir: sharedDir || "" }),
  androidSync: () => api.post("/api/android/sync", {}),
  androidImport: () => api.post("/api/android/import", {}),
  eventsHistory: (since = 0) => api.get("/api/events/history?since=" + encodeURIComponent(since)),
  fileDialog: (kind, title, initial) =>
    api.post("/api/files/dialog", { kind, title: title || "", initial: initial || "" }, { timeoutMs: 600000 }),
};
