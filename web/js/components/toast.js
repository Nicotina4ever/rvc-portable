/* RVC Portable — toast non bloccanti. */
import { h, icon } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { btn } from "./ui.js";

let root = null;
const MAX_VISIBLE = 4;
const ICONS = { success: "check", error: "alert", warning: "alert", info: "info" };

function remove(node) {
  if (!node || !node.isConnected) return;
  node.classList.remove("is-visible");
  setTimeout(() => node.remove(), 220);
}

export function initToasts(node) {
  root = node;
}

export function showToast(options) {
  if (!root) return null;
  const config = typeof options === "string" ? { message: options } : options || {};
  const level = ["success", "error", "warning", "info"].includes(config.level) ? config.level : "info";
  const message = String(config.message || "");
  const detail = config.detail ? String(config.detail) : "";
  const timeout = config.timeout === undefined ? (level === "error" ? 7000 : 4200) : config.timeout;

  while (root.children.length >= MAX_VISIBLE) root.firstElementChild.remove();

  const node = h(
    "div",
    { class: "toast toast-" + level, role: level === "error" ? "alert" : "status" },
    h("span", { class: "toast-icon" }, icon(ICONS[level] || "info")),
    h(
      "div",
      { class: "toast-text" },
      h("p", { class: "toast-message", text: message }),
      detail ? h("p", { class: "toast-detail", text: detail }) : null
    ),
    btn("", {
      variant: "ghost",
      iconName: "x",
      ariaLabel: t("common.close"),
      className: "toast-close",
      onClick: () => remove(node),
    })
  );
  root.appendChild(node);
  requestAnimationFrame(() => node.classList.add("is-visible"));
  if (timeout > 0) setTimeout(() => remove(node), timeout);
  return node;
}

export const toast = {
  show: showToast,
  info: (message, detail) => showToast({ level: "info", message, detail }),
  success: (message, detail) => showToast({ level: "success", message, detail }),
  warning: (message, detail) => showToast({ level: "warning", message, detail }),
  error: (errorOrMessage, detail) => {
    if (errorOrMessage instanceof Error) {
      showToast({ level: "error", message: errorFull(errorOrMessage) });
      return;
    }
    showToast({ level: "error", message: String(errorOrMessage || t("errors.generic")), detail });
  },
};
