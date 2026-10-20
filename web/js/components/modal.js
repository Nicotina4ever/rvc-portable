/* RVC Portable — dialoghi modali (conferme distruttive e pannelli informativi). */
import { h, clear, icon, div } from "../core/dom.js";
import { t } from "../core/i18n.js";

let dialog = null;
let pendingResolve = null;

function closeButton() {
  return h(
    "button",
    { class: "btn btn-ghost btn-icon modal-close", type: "submit", value: "cancel", "aria-label": t("common.close") },
    icon("x")
  );
}

function prepare(title) {
  clear(dialog);
  const form = h("form", { method: "dialog", class: "modal-card" });
  const header = h("div", { class: "modal-header" }, h("h2", { class: "modal-title", id: "modal-title", text: title }), closeButton());
  const body = div("modal-body");
  const footer = div("modal-footer");
  form.append(header, body, footer);
  dialog.appendChild(form);
  dialog.setAttribute("aria-labelledby", "modal-title");
  return { body, footer };
}

function open(resolve) {
  pendingResolve = resolve;
  try {
    dialog.showModal();
  } catch (err) {
    pendingResolve = null;
    resolve(false);
  }
}

export function initModal(node) {
  dialog = node;
  dialog.addEventListener("close", () => {
    const resolve = pendingResolve;
    pendingResolve = null;
    if (resolve) resolve(dialog.returnValue === "confirm");
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close("cancel");
  });
}

/** Conferma modale: true se l'utente conferma. */
export function confirmModal(options = {}) {
  if (!dialog) return Promise.resolve(false);
  const {
    title = "",
    message = "",
    detail = "",
    confirmLabel = t("common.confirm"),
    cancelLabel = t("common.cancel"),
    danger = false,
  } = options;
  return new Promise((resolve) => {
    const prepared = prepare(title);
    prepared.body.appendChild(h("p", { class: "modal-message", text: message }));
    if (detail) prepared.body.appendChild(h("p", { class: "modal-detail", text: detail }));
    prepared.footer.append(
      h("button", { class: "btn btn-secondary", type: "submit", value: "cancel", text: cancelLabel }),
      h("button", {
        class: "btn " + (danger ? "btn-danger" : "btn-primary"),
        type: "submit",
        value: "confirm",
        text: confirmLabel,
        autofocus: true,
      })
    );
    if (dialog.open) dialog.close("cancel");
    open(resolve);
  });
}

/** Pannello con contenuto personalizzato (es. aiuto/scorciatoie). */
export function panelModal(options = {}) {
  if (!dialog) return Promise.resolve(false);
  const { title = "", content = null, okLabel = t("common.close") } = options;
  return new Promise((resolve) => {
    const prepared = prepare(title);
    if (content instanceof Node) prepared.body.appendChild(content);
    else prepared.body.appendChild(h("p", { class: "modal-message", text: String(content || "") }));
    prepared.footer.append(h("button", { class: "btn btn-primary", type: "submit", value: "confirm", text: okLabel }));
    if (dialog.open) dialog.close("cancel");
    open(resolve);
  });
}
