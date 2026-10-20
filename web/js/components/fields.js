/* RVC Portable — campi form accessibili e coerenti. */
import { h, div, span, icon, uid, clamp, setAttr } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { btn } from "./ui.js";
import { toast } from "./toast.js";

function fieldShell(options) {
  const { label = "", hint = "", control, id = "", describedTarget = null, error = "", className = "" } = options;
  const hintId = hint ? uid("hint") : "";
  const errorId = uid("error");
  const labelNode = label ? h("label", { class: "field-label", for: id }, label) : null;
  const hintNode = hint ? h("p", { class: "field-hint", id: hintId, text: hint }) : null;
  const errorNode = h("p", { class: "field-error", id: errorId, hidden: true });
  if (describedTarget) {
    const described = [hintId, errorId].filter(Boolean).join(" ");
    if (described) setAttr(describedTarget, "aria-describedby", described);
  }
  const shell = div("field" + (className ? " " + className : ""), labelNode, div("field-control", control), hintNode, errorNode);
  shell.setError = (message) => {
    const hasError = Boolean(message);
    shell.classList.toggle("has-error", hasError);
    errorNode.hidden = !hasError;
    errorNode.textContent = hasError ? message : "";
    if (describedTarget) describedTarget.setAttribute("aria-invalid", hasError ? "true" : "false");
  };
  return shell;
}

export function textField(options = {}) {
  const {
    id = uid("field"),
    label = "",
    value = "",
    placeholder = "",
    hint = "",
    type = "text",
    mono = false,
    required = false,
    onInput = null,
    className = "",
  } = options;
  const input = h("input", {
    id,
    class: "input" + (mono ? " input-mono" : ""),
    type,
    value: value === null || value === undefined ? "" : String(value),
    placeholder: placeholder || "",
    autocomplete: "off",
    spellcheck: "false",
    required: required || null,
  });
  if (onInput) input.addEventListener("input", () => onInput(input.value));
  const shell = fieldShell({ label, hint, control: input, id, describedTarget: input, className });
  return {
    el: shell,
    input,
    getValue: () => input.value,
    setValue: (next) => {
      input.value = next === null || next === undefined ? "" : String(next);
    },
    setError: (message) => shell.setError(message),
  };
}

/** Campo percorso con pulsante "Sfoglia" (dialog nativo del backend). */
export function pathField(options = {}) {
  const {
    id = uid("field"),
    label = "",
    value = "",
    placeholder = "",
    hint = "",
    kind = "directory",
    dialogTitle = "",
    required = false,
    onChange = null,
    browseLabel = "",
  } = options;
  const input = h("input", {
    id,
    class: "input input-mono",
    type: "text",
    value: value === null || value === undefined ? "" : String(value),
    placeholder: placeholder || t("common.path"),
    autocomplete: "off",
    spellcheck: "false",
    required: required || null,
  });
  const browseButton = btn(browseLabel || t("common.browse"), {
    variant: "secondary",
    iconName: "folder",
    className: "path-browse",
  });
  browseButton.addEventListener("click", async () => {
    if (browseButton.disabled) return;
    browseButton.disabled = true;
    browseButton.classList.add("is-busy");
    try {
      const result = await endpoints.fileDialog(kind, dialogTitle || label, input.value);
      if (result && !result.canceled && result.path) {
        input.value = result.path;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        if (onChange) onChange(result.path);
      }
    } catch (err) {
      toast.show({
        level: "error",
        message: t("config.browseFailed"),
        detail: errorFull(err),
      });
    } finally {
      browseButton.disabled = false;
      browseButton.classList.remove("is-busy");
    }
  });
  input.addEventListener("input", () => {
    if (onChange) onChange(input.value);
  });
  const row = div("path-row", input, browseButton);
  const shell = fieldShell({ label, hint, control: row, id, describedTarget: input });
  return {
    el: shell,
    input,
    browseButton,
    getValue: () => input.value,
    setValue: (next) => {
      input.value = next === null || next === undefined ? "" : String(next);
    },
    setError: (message) => shell.setError(message),
  };
}

/* ------------------------------------------------------------------- slider */

function decimalsFor(step) {
  const text = String(step);
  if (text.includes(".")) return text.split(".")[1].length;
  return 0;
}

function snap(value, min, max, step) {
  const number = Number(value);
  if (!Number.isFinite(number)) return min;
  const base = Math.round((clamp(number, min, max) - min) / step) * step + min;
  return Number(base.toFixed(Math.min(6, decimalsFor(step))));
}

export function rangeField(options = {}) {
  const {
    id = uid("field"),
    label = "",
    min = 0,
    max = 1,
    step = 0.01,
    value = min,
    hint = "",
    format = null,
    onChange = null,
  } = options;
  const range = h("input", { type: "range", class: "range", id: id + "-range", min, max, step, "aria-label": label });
  const number = h("input", { type: "number", class: "input input-number", id, min, max, step, inputmode: "decimal" });
  const output = span("range-value");
  const initial = snap(value, min, max, step);
  range.value = String(initial);
  number.value = String(initial);
  const display = (val) => (typeof format === "function" ? format(val) : String(val));
  output.textContent = display(initial);

  const apply = (raw, source) => {
    const next = snap(raw, min, max, step);
    if (source !== range) range.value = String(next);
    if (source !== number) number.value = String(next);
    output.textContent = display(next);
    if (onChange) onChange(next);
    return next;
  };
  range.addEventListener("input", () => apply(range.value, range));
  number.addEventListener("input", () => {
    if (number.value === "" || number.value === "-") return;
    apply(number.value, number);
  });
  number.addEventListener("change", () => apply(number.value, number));

  const labelRow = div("field-label-row", h("label", { class: "field-label", for: id, text: label }), output);
  const row = div("slider-row", range, number);
  const hintNode = hint ? h("p", { class: "field-hint", text: hint }) : null;
  const shell = div("field field-range", labelRow, row, hintNode);
  return {
    el: shell,
    range,
    number,
    getValue: () => Number(range.value),
    setValue: (next) => apply(next, null),
    setError: (message) => shell.classList.toggle("has-error", Boolean(message)),
  };
}

/* ------------------------------------------------------------------- select */

export function selectField(options = {}) {
  const {
    id = uid("field"),
    label = "",
    value = "",
    options: items = [],
    hint = "",
    onChange = null,
    includeEmpty = false,
    emptyLabel = "",
  } = options;
  const select = h("select", { class: "select", id });
  if (includeEmpty) select.appendChild(h("option", { value: "", text: emptyLabel || t("common.none") }));
  for (const item of items) {
    const option = h("option", { value: String(item.value), text: item.label });
    if (String(item.value) === String(value)) option.selected = true;
    select.appendChild(option);
  }
  if (onChange) select.addEventListener("change", () => onChange(select.value));
  const shell = fieldShell({ label, hint, control: select, id, describedTarget: select });
  return {
    el: shell,
    select,
    getValue: () => select.value,
    setValue: (next) => {
      select.value = next === null || next === undefined ? "" : String(next);
    },
    setError: (message) => shell.setError(message),
  };
}

/* ------------------------------------------------------------------- switch */

export function switchField(options = {}) {
  const {
    id = uid("field"),
    label = "",
    checked = false,
    hint = "",
    onChange = null,
    disabled = false,
  } = options;
  const input = h("input", { type: "checkbox", class: "switch-input", id, disabled: disabled || null });
  input.checked = Boolean(checked);
  if (onChange) input.addEventListener("change", () => onChange(input.checked));
  const control = h(
    "label",
    { class: "switch", for: id },
    input,
    span("switch-track", icon("check", "switch-check")),
    span("switch-label", label)
  );
  const shell = div("field field-switch", control, hint ? h("p", { class: "field-hint", text: hint }) : null);
  return {
    el: shell,
    input,
    getValue: () => input.checked,
    setValue: (next) => {
      input.checked = Boolean(next);
    },
  };
}

/* ---------------------------------------------------------------- search box */

export function searchField(options = {}) {
  const { placeholder = t("common.search"), onInput = null, ariaLabel = "" } = options;
  const input = h("input", {
    type: "search",
    class: "input input-search",
    placeholder,
    autocomplete: "off",
    "aria-label": ariaLabel || placeholder,
  });
  if (onInput) input.addEventListener("input", () => onInput(input.value));
  return input;
}

export function requiredMark() {
  return span("required-mark", "*");
}
