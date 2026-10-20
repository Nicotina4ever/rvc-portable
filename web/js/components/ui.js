/* RVC Portable — componenti UI di base. */
import { h, div, span, icon, clear } from "../core/dom.js";
import { t } from "../core/i18n.js";

export function btn(label, options = {}) {
  const {
    variant = "secondary",
    iconName = "",
    onClick = null,
    title = "",
    ariaLabel = "",
    type = "button",
    disabled = false,
    id = "",
    className = "",
  } = options;
  const classes = ["btn", "btn-" + variant];
  if (className) classes.push(className);
  if (iconName && !label) classes.push("btn-icon");
  const node = h(
    "button",
    {
      class: classes.join(" "),
      type,
      id: id || null,
      title: title || null,
      disabled: disabled || null,
      "aria-label": ariaLabel || (!label && title ? title : null),
    },
    iconName ? icon(iconName) : null,
    label ? span("btn-label", label) : null
  );
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

export function card(options = {}) {
  const { title = "", subtitle = "", actions = null, children = [], className = "", id = "" } = options;
  const node = div("card" + (className ? " " + className : ""), null);
  if (id) node.id = id;
  if (title || actions || subtitle) {
    const heading = h(
      "div",
      { class: "card-heading" },
      title ? h("h2", { class: "card-title", text: title }) : null,
      subtitle ? h("p", { class: "card-subtitle", text: subtitle }) : null
    );
    node.appendChild(h("header", { class: "card-header" }, heading, actions ? h("div", { class: "card-actions" }, actions) : null));
  }
  const body = div("card-body", children);
  node.appendChild(body);
  node.body = body;
  return node;
}

export function badge(text, variant = "neutral") {
  return span("badge badge-" + variant, text);
}

export function statusBadge(kind) {
  const map = {
    ok: ["badge-ok", t("status.ok")],
    warn: ["badge-warn", t("status.warn")],
    fail: ["badge-bad", t("status.error")],
    error: ["badge-bad", t("status.error")],
    info: ["badge-info", t("status.info")],
  };
  const entry = map[kind] || ["badge-neutral", String(kind || t("common.unknown"))];
  return badge(entry[1], entry[0].replace("badge-", ""));
}

export function emptyState(options = {}) {
  const { iconName = "info", title = "", text = "", detail = "", actions = [] } = options;
  return div(
    "empty-state",
    span("empty-icon", icon(iconName)),
    title ? h("h3", { class: "empty-title", text: title }) : null,
    text ? h("p", { class: "empty-text", text }) : null,
    detail ? h("p", { class: "empty-detail", text: detail }) : null,
    actions.length ? div("empty-actions", actions) : null
  );
}

export function progressBar(value, label) {
  const node = h("progress", {
    class: "progress",
    max: "100",
    "aria-label": label || t("common.loading"),
  });
  if (value !== null && value !== undefined && Number.isFinite(Number(value))) {
    node.value = Math.max(0, Math.min(100, Number(value)));
  }
  return node;
}

export function loadingBlock(text) {
  return div(
    "loading-block",
    span("spinner"),
    h("p", { class: "loading-text", text: text || t("common.loading") })
  );
}

export function kvRow(label, value) {
  const valueNode = value instanceof Node ? value : h("span", { class: "kv-value", text: value === null || value === undefined || value === "" ? "—" : String(value) });
  return div("kv", h("span", { class: "kv-label", text: label }), valueNode);
}

export function toolbar(children) {
  return div("toolbar", children);
}

export function sectionTitle(title, subtitle) {
  return h(
    "div",
    { class: "section-title" },
    h("h2", { class: "section-heading", text: title }),
    subtitle ? h("p", { class: "section-subtitle", text: subtitle }) : null
  );
}

export function setProgress(node, value) {
  if (!node) return;
  const number = Number(value);
  if (!Number.isFinite(number)) {
    node.removeAttribute("value");
    return;
  }
  node.value = Math.max(0, Math.min(100, number));
}

export function replaceContent(node, ...children) {
  clear(node);
  node.appendChild(div("content", ...children));
  return node;
}
