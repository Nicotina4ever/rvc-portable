/* RVC Portable — vista Setup: primo avvio guidato in tre passaggi. */
import { h, div, span, icon, clear } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { state } from "../core/store.js";
import { patchSettings } from "../core/settings.js";
import { card, btn, badge, emptyState } from "../components/ui.js";
import { pathField } from "../components/fields.js";
import { toast } from "../components/toast.js";

const STEP_KEYS = ["setup.stepData", "setup.stepDevice", "setup.stepModel"];
const DEVICES = [
  { value: "auto", labelKey: "setup.deviceAuto", hintKey: "setup.deviceAutoHint" },
  { value: "cuda:0", labelKey: "advanced.deviceCuda", hintKey: "setup.deviceCudaHint" },
  { value: "cpu", labelKey: "advanced.deviceCpu", hintKey: "setup.deviceCpuHint" },
  { value: "mps", labelKey: "advanced.deviceMps", hintKey: "setup.deviceMpsHint" },
];

export const setupView = {
  id: "setup",
  titleKey: "nav.setup",

  async mount(root, ctx) {
    let step = 0;
    let saving = false;
    const audio = (state.settings && state.settings.audio) || {};
    const engine = (state.settings && state.settings.engine) || {};
    let selectedDevice = engine.device || "auto";

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("setup.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("setup.subtitle") });
    const skipButton = btn(t("setup.skip"), { variant: "ghost", onClick: () => skip() });
    const backButton = btn(t("setup.back"), { variant: "secondary", iconName: "arrow-left", onClick: () => goStep(step - 1) });
    const nextButton = btn(t("common.next"), { variant: "primary", iconName: "arrow-right", onClick: () => goStep(step + 1) });
    const finishButton = btn(t("setup.finish"), { variant: "primary", iconName: "check", onClick: () => finish() });

    const header = div("view-header", div("view-heading", title, subtitle), div("view-actions", skipButton));

    const stepLabel = h("p", { class: "setup-step-label" });
    const stepper = div("stepper");
    const stepNodes = STEP_KEYS.map((key, index) => {
      const node = h("span", { class: "step" }, badge(String(index + 1), "neutral"), h("span", { class: "step-title", text: t(key) }));
      stepper.appendChild(node);
      return node;
    });

    /* ------------------------------------------------------------ step data */
    const inputField = pathField({
      id: "setup-input",
      label: t("setup.inputDir"),
      value: audio.input_dir || "",
      kind: "directory",
    });
    const outputField = pathField({
      id: "setup-output",
      label: t("setup.outputDir"),
      value: audio.output_dir || "",
      kind: "directory",
    });
    const dataStep = card({
      title: t("setup.stepData"),
      subtitle: t("setup.dataHint"),
      children: [div("field-grid", inputField.el, outputField.el)],
    });

    /* ---------------------------------------------------------- step device */
    const deviceGrid = div("device-cards");
    const deviceInputs = [];
    for (const device of DEVICES) {
      const inputId = "setup-device-" + device.value.replace(/[^a-z0-9]/gi, "-");
      const input = h("input", { type: "radio", name: "setup-device", id: inputId, value: device.value, class: "device-radio" });
      input.checked = selectedDevice === device.value;
      input.addEventListener("change", () => {
        selectedDevice = device.value;
        renderStepper();
      });
      deviceInputs.push(input);
      deviceGrid.appendChild(
        h(
          "label",
          { class: "device-card", for: inputId },
          input,
          div("device-card-text", h("span", { class: "device-card-title", text: t(device.labelKey) }), h("span", { class: "device-card-hint", text: t(device.hintKey) }))
        )
      );
    }
    const deviceStep = card({ title: t("setup.stepDevice"), subtitle: t("setup.deviceHint"), children: [deviceGrid] });

    /* ----------------------------------------------------------- step model */
    const modelField = pathField({
      id: "setup-model",
      label: t("setup.modelPath"),
      value: audio.model_path || "",
      kind: "model",
    });
    const indexField = pathField({
      id: "setup-index",
      label: t("setup.indexPath"),
      value: audio.index_path || "",
      hint: t("setup.indexHint"),
      kind: "index",
    });
    const diagLink = btn(t("setup.diagnostics"), {
      variant: "ghost",
      iconName: "activity",
      onClick: () => ctx.navigate("advanced", { runDiagnostics: true }),
    });
    const modelStep = card({
      title: t("setup.stepModel"),
      subtitle: t("setup.modelHint"),
      children: [div("field-grid", modelField.el, indexField.el), div("button-row", diagLink)],
    });

    const errorBox = h("p", { class: "inline-alert", hidden: true });
    const stepHost = div("setup-steps", dataStep, deviceStep, modelStep);
    const footer = div("setup-footer", backButton, div("setup-footer-right", nextButton, finishButton));
    const panel = div("setup-panel", stepLabel, stepper, errorBox, stepHost, footer);
    root.append(header, panel);

    function showError(message) {
      errorBox.hidden = !message;
      errorBox.textContent = message || "";
    }

    function renderStepper() {
      stepLabel.textContent = t("setup.step", { current: step + 1, total: STEP_KEYS.length });
      stepNodes.forEach((node, index) => {
        node.classList.toggle("is-active", index === step);
        node.classList.toggle("is-done", index < step);
        const badgeNode = node.querySelector(".badge");
        if (badgeNode) {
          badgeNode.className = "badge badge-" + (index === step ? "accent" : index < step ? "ok" : "neutral");
        }
      });
      dataStep.hidden = step !== 0;
      deviceStep.hidden = step !== 1;
      modelStep.hidden = step !== 2;
      backButton.hidden = step === 0;
      nextButton.hidden = step === STEP_KEYS.length - 1;
      finishButton.hidden = step !== STEP_KEYS.length - 1;
      showError("");
    }

    function validateStep(index) {
      if (index === 0) {
        if (!inputField.getValue().trim()) {
          showError(t("monitor.dirRequired"));
          return false;
        }
        if (!outputField.getValue().trim()) {
          showError(t("setup.requiredHint"));
          return false;
        }
      }
      if (index === 2 && !modelField.getValue().trim()) {
        showError(t("setup.requiredHint"));
        return false;
      }
      return true;
    }

    function goStep(next) {
      const target = Math.max(0, Math.min(STEP_KEYS.length - 1, next));
      if (target > step && !validateStep(step)) return;
      step = target;
      renderStepper();
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    function skip() {
      try {
        sessionStorage.setItem("rvc.setupDismissed", "1");
      } catch (err) {
        /* storage non disponibile */
      }
      state.setupDismissed = true;
      ctx.navigate("dashboard");
    }

    async function finish() {
      if (saving) return;
      if (!inputField.getValue().trim()) {
        step = 0;
        renderStepper();
        showError(t("monitor.dirRequired"));
        return;
      }
      if (!modelField.getValue().trim()) {
        step = 2;
        renderStepper();
        showError(t("setup.requiredHint"));
        return;
      }
      saving = true;
      finishButton.disabled = true;
      try {
        await patchSettings({
          audio: {
            input_dir: inputField.getValue().trim(),
            output_dir: outputField.getValue().trim(),
            model_path: modelField.getValue().trim(),
            index_path: indexField.getValue().trim(),
          },
          engine: { device: selectedDevice },
        });
        try {
          sessionStorage.setItem("rvc.setupDismissed", "1");
        } catch (err) {
          /* storage non disponibile */
        }
        state.setupDismissed = true;
        toast.success(t("setup.done"));
        ctx.navigate("dashboard");
      } catch (err) {
        toast.show({ level: "error", message: t("setup.saveFailed"), detail: errorFull(err) });
      } finally {
        saving = false;
        finishButton.disabled = false;
      }
    }

    renderStepper();

    return () => {
      /* niente da liberare */
    };
  },
};
