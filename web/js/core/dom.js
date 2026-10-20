/* RVC Portable — helper DOM e formattazione. Nessuna dipendenza esterna. */
import { getLanguage, t } from "./i18n.js";

export const SVG_NS = "http://www.w3.org/2000/svg";

function appendChild(node, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) {
    child.forEach((item) => appendChild(node, item));
    return;
  }
  if (child instanceof Node) {
    node.appendChild(child);
    return;
  }
  node.appendChild(document.createTextNode(String(child)));
}

/** Crea un elemento con attributi/eventi e figli. */
export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs && typeof attrs === "object") {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = String(value);
      else if (key === "dataset") Object.assign(node.dataset, value);
      else if (key === "html") node.innerHTML = value; /* solo markup interno fidato */
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) node.setAttribute(key, "");
      else node.setAttribute(key, String(value));
    }
  }
  appendChild(node, children);
  return node;
}

export function div(className, ...children) {
  return h("div", { class: className }, ...children);
}

export function span(className, ...children) {
  return h("span", { class: className }, ...children);
}

export function clear(node) {
  if (!node) return node;
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/** Come Element.append ma ignora null/undefined/false (evita il testo "null"). */
export function appendAll(parent, ...children) {
  children.forEach((child) => appendChild(parent, child));
  return parent;
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function on(target, type, handler, options) {
  target.addEventListener(type, handler, options);
  return () => target.removeEventListener(type, handler, options);
}

export function setText(node, text) {
  if (node && node.textContent !== String(text)) node.textContent = String(text);
  return node;
}

export function setAttr(node, name, value) {
  if (!node) return node;
  if (value === null || value === undefined || value === false) node.removeAttribute(name);
  else node.setAttribute(name, String(value));
  return node;
}

export function toggleClass(node, className, active) {
  if (!node) return node;
  node.classList.toggle(className, Boolean(active));
  return node;
}

/** Icona SVG inline dal set di simboli in index.html. */
export function icon(name, extraClass = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", ("icon icon-" + name + " " + extraClass).trim());
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", "#i-" + name);
  svg.appendChild(use);
  return svg;
}

export function spinner(extraClass = "") {
  return span("spinner " + extraClass, h("span", { class: "sr-only", text: t("common.loading") }));
}

export function uid(prefix = "id") {
  uid.counter = (uid.counter || 0) + 1;
  return prefix + "-" + uid.counter + "-" + Math.random().toString(36).slice(2, 7);
}

/* --------------------------------------------------------------- formattazione */

export function toDate(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return null;
  const ms = number > 1e12 ? number : number * 1000;
  const date = new Date(ms);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function localeTag() {
  return getLanguage() === "it" ? "it-IT" : "en-US";
}

export function formatDateTime(value) {
  const date = toDate(value);
  if (!date) return "—";
  try {
    return new Intl.DateTimeFormat(localeTag(), { dateStyle: "short", timeStyle: "short" }).format(date);
  } catch (err) {
    return date.toLocaleString();
  }
}

export function formatClock(value) {
  const date = toDate(value);
  if (!date) return "--:--:--";
  try {
    return new Intl.DateTimeFormat(localeTag(), { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
  } catch (err) {
    return date.toLocaleTimeString();
  }
}

export function timeAgo(value) {
  const date = toDate(value);
  if (!date) return t("common.never");
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (Math.abs(seconds) < 45) return t("common.justNow");
  try {
    const rtf = new Intl.RelativeTimeFormat(getLanguage(), { numeric: "auto" });
    const minutes = Math.round(seconds / 60);
    if (Math.abs(minutes) < 60) return rtf.format(-minutes, "minute");
    const hours = Math.round(minutes / 60);
    if (Math.abs(hours) < 24) return rtf.format(-hours, "hour");
    const days = Math.round(hours / 24);
    if (Math.abs(days) < 30) return rtf.format(-days, "day");
    const months = Math.round(days / 30);
    if (Math.abs(months) < 12) return rtf.format(-months, "month");
    return rtf.format(-Math.round(months / 12), "year");
  } catch (err) {
    return formatDateTime(value);
  }
}

/** Durata mm:ss / h:mm:ss. */
export function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(secs).padStart(2, "0");
  return hours > 0 ? hours + ":" + mm + ":" + ss : minutes + ":" + ss;
}

export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  try {
    return new Intl.NumberFormat(localeTag()).format(number);
  } catch (err) {
    return String(number);
  }
}

export function formatMb(value) {
  if (value === null || value === undefined || value === "") return "—";
  const mb = Number(value);
  if (!Number.isFinite(mb)) return "—";
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
  return mb.toFixed(1) + " MB";
}

export function basename(path) {
  const text = String(path || "").replace(/[\\/]+$/, "");
  if (!text) return "";
  const parts = text.split(/[\\/]/);
  return parts[parts.length - 1] || text;
}

export function dirname(path) {
  const text = String(path || "").replace(/[\\/]+$/, "");
  const index = Math.max(text.lastIndexOf("/"), text.lastIndexOf("\\"));
  return index > 0 ? text.slice(0, index) : text;
}

export function truncateMiddle(text, max = 48) {
  const value = String(text || "");
  if (value.length <= max) return value;
  const head = Math.ceil((max - 1) / 2);
  const tail = Math.floor((max - 1) / 2);
  return value.slice(0, head) + "…" + value.slice(value.length - tail);
}

/* ------------------------------------------------------------------ utility */

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function debounce(fn, wait = 250) {
  let timer = null;
  const wrapped = (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, wait);
  };
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return wrapped;
}

export function isTypingTarget(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || Boolean(target.isContentEditable);
}

export function isInteractiveTarget(target) {
  if (isTypingTarget(target)) return true;
  if (!target) return false;
  if (target.isContentEditable) return true;
  const tag = (target.tagName || "").toLowerCase();
  if (["button", "a", "summary", "label", "option"].includes(tag)) return true;
  const role = target.getAttribute ? target.getAttribute("role") : "";
  return ["button", "tab", "switch", "checkbox", "radio", "menuitem"].includes(role || "");
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = h("a", { href: url, download: filename, class: "sr-only" });
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function copyText(text) {
  const value = String(text || "");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(value).then(() => true).catch(() => false);
  }
  return Promise.resolve(false);
}

export function errorSummary(err) {
  return String((err && (err.message || err.code)) || t("errors.generic"));
}
