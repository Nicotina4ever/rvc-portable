/* RVC Portable — trasporto SSE con riconnessione e Last-Event-ID. */
import { getToken } from "./api.js";

const EVENT_TYPES = ["hello", "log", "job", "job_log", "monitor", "config", "engine", "toast"];
const LAST_KEY = "rvc.lastEventId";

let lastId = 0;
try {
  lastId = Number(sessionStorage.getItem(LAST_KEY) || 0) || 0;
} catch (err) {
  lastId = 0;
}

let source = null;
let retryTimer = null;
let attempts = 0;
let currentOptions = null;
let stopped = true;

function persistLastId() {
  try {
    sessionStorage.setItem(LAST_KEY, String(lastId));
  } catch (err) {
    /* storage non disponibile */
  }
}

export function getLastEventId() {
  return lastId;
}

export function setLastEventId(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return;
  lastId = number;
  persistLastId();
}

/** Il server è ripartito (id più bassi): allinea l'id senza perdere eventi futuri. */
export function noteServerLastId(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return;
  if (number < lastId) lastId = number;
  else lastId = Math.max(lastId, number);
  persistLastId();
}

function buildUrl() {
  const params = new URLSearchParams();
  params.set("since", String(lastId));
  const token = getToken();
  if (token) params.set("t", token);
  return "/api/events?" + params.toString();
}

function scheduleReconnect() {
  if (stopped) return;
  if (retryTimer) clearTimeout(retryTimer);
  attempts += 1;
  const base = Math.min(30000, 1000 * Math.pow(1.8, attempts));
  const delay = base + Math.random() * 500;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    openSource();
  }, delay);
}

function openSource() {
  if (stopped || !currentOptions) return;
  closeSource();
  currentOptions.onStatus("connecting");
  let eventSource;
  try {
    eventSource = new EventSource(buildUrl());
  } catch (err) {
    currentOptions.onStatus("offline");
    scheduleReconnect();
    return;
  }
  source = eventSource;
  eventSource.addEventListener("open", () => {
    attempts = 0;
    currentOptions.onStatus("connected");
  });
  eventSource.addEventListener("error", () => {
    if (source !== eventSource) return;
    eventSource.close();
    source = null;
    if (!stopped) {
      currentOptions.onStatus("offline");
      scheduleReconnect();
    }
  });
  for (const type of EVENT_TYPES) {
    eventSource.addEventListener(type, (event) => {
      const rawId = Number(event.lastEventId);
      if (Number.isFinite(rawId) && rawId > lastId) {
        lastId = rawId;
        persistLastId();
      }
      let data = {};
      try {
        data = JSON.parse(event.data || "{}");
      } catch (err) {
        data = {};
      }
      try {
        currentOptions.onEvent(type, data);
      } catch (err) {
        console.error("gestione evento SSE fallita:", type, err);
      }
    });
  }
}

function closeSource() {
  if (source) {
    try {
      source.close();
    } catch (err) {
      /* già chiusa */
    }
    source = null;
  }
}

export function connectEvents(options) {
  currentOptions = options;
  stopped = false;
  attempts = 0;
  openSource();
}

export function disconnectEvents() {
  stopped = true;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  closeSource();
}

/** Storico eventi (se l'endpoint ausiliario è disponibile) per popolare il log. */
export async function seedHistory() {
  try {
    const response = await fetch("/api/events/history?since=0", {
      headers: getToken() ? { Authorization: "Bearer " + getToken() } : {},
      cache: "no-store",
    });
    if (!response.ok) return [];
    const data = await response.json();
    const events = Array.isArray(data.events) ? data.events : [];
    const last = Number(data.last_id || 0);
    if (Number.isFinite(last) && last > lastId) setLastEventId(last);
    return events;
  } catch (err) {
    return [];
  }
}
