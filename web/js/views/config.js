/* RVC Portable — vista Configurazione. */
import { h, div, span, icon, clear, basename } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { state, subscribe } from "../core/store.js";
import { loadSettings, patchSettings } from "../core/settings.js";
import { card, btn, badge, emptyState, kvRow } from "../components/ui.js";
import { textField, pathField, rangeField, selectField } from "../components/fields.js";
import { toast } from "../components/toast.js";
import { downloadBlob } from "../core/dom.js";

const METHODS = [
  { value: "rmvpe", label: "RMVPE" },
  { value: "harvest", label: "Harvest" },
  { value: "crepe", label: "CREPE" },
  { value: "pm", label: "PM" },
];

const OUTPUT_FORMATS = [
  { value: "wav", label: "WAV" },
  { value: "flac", label: "FLAC" },
];

const MODEL_VERSIONS = [
  { value: "v2", label: "v2" },
  { value: "v1", label: "v1" },
];

let preservedDraft = null;
let preservedDirty = false;

export const configView = {
  id: "config",
  titleKey: "nav.config",

  async mount(root, ctx) {
    let unsub = null;
    let fields = null;
    let dirty = Boolean(preservedDirty);
    let localExternal = null;

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("config.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("config.subtitle") });
    const unsavedBadge = badge(t("config.unsaved"), "warn");
    unsavedBadge.hidden = !dirty;

    const saveButton = btn(t("config.save"), { variant: "primary", iconName: "save", onClick: () => save() });
    const exportButton = btn(t("config.export"), { variant: "secondary", iconName: "download", onClick: () => exportConfig() });
    const importButton = btn(t("config.import"), { variant: "secondary", iconName: "upload", onClick: () => importInput.click() });
    const reloadButton = btn(t("common.reload"), { variant: "ghost", iconName: "refresh", onClick: () => reloadSettings() });
    const importInput = h("input", { type: "file", accept: ".json,application/json", class: "sr-only", "aria-label": t("config.import") });

    const header = div(
      "view-header",
      div("view-heading", title, subtitle),
      div("view-actions", unsavedBadge, reloadButton, importButton, exportButton, saveButton)
    );

    const bannerHost = div("banner-host");
    const warningsHost = div("warnings-host");
    const formHost = div("config-form");

    root.append(header, importInput, bannerHost, warningsHost, formHost);

    function setDirty(next) {
      dirty = Boolean(next);
      unsavedBadge.hidden = !dirty;
    }

    async function presetAndroid() {
      if (dirty && !window.confirm(t("config.presetConfirm"))) return;
      try {
        const result = await endpoints.androidPreset("");
        toast.success(t("android.presetDone"));
        const status = result && result.status;
        if (status && status.shared_dir) {
          setDirty(false);
          window.location.reload();
        }
      } catch (err) {
        toast.error(err);
      }
    }

    function readDraft() {
      if (!fields) return null;
      return {
        input_dir: fields.inputDir.getValue().trim(),
        output_dir: fields.outputDir.getValue().trim(),
        model_path: fields.modelPath.getValue().trim(),
        index_path: fields.indexPath.getValue().trim(),
        model_version: fields.modelVersion.getValue(),
        pitch: fields.pitch.getValue(),
        method: fields.method.getValue(),
        protect: fields.protect.getValue(),
        index_rate: fields.indexRate.getValue(),
        filter_radius: fields.filterRadius.getValue(),
        rms_mix_rate: fields.rmsMixRate.getValue(),
        resample_sr: fields.resampleSr.getValue(),
        output_format: fields.outputFormat.getValue(),
      };
    }

    function draftFromSettings() {
      const audio = (state.settings && state.settings.audio) || {};
      return {
        input_dir: audio.input_dir || "",
        output_dir: audio.output_dir || "",
        model_path: audio.model_path || "",
        index_path: audio.index_path || "",
        model_version: audio.model_version || "v2",
        pitch: audio.pitch || 0,
        method: METHODS.some((item) => item.value === audio.method) ? audio.method : "rmvpe",
        protect: audio.protect !== undefined ? audio.protect : 0.33,
        index_rate: audio.index_rate !== undefined ? audio.index_rate : 0.3,
        filter_radius: audio.filter_radius !== undefined ? audio.filter_radius : 3,
        rms_mix_rate: audio.rms_mix_rate !== undefined ? audio.rms_mix_rate : 0.25,
        resample_sr: audio.resample_sr || 0,
        output_format: audio.output_format === "flac" ? "flac" : "wav",
      };
    }

    function renderBanner() {
      clear(bannerHost);
      const external = localExternal || state.externalConfig;
      if (!external) return;
      const path = external.path || (state.settingsMeta && state.settingsMeta.config_path) || "";
      bannerHost.appendChild(
        h(
          "div",
          { class: "banner banner-warn", role: "status" },
          span("banner-icon", icon("alert")),
          div(
            "banner-content",
            h("p", { class: "banner-title", text: t("config.externalTitle") }),
            h("p", { class: "banner-text", text: t("config.externalText", { path }) })
          ),
          div(
            "banner-actions",
            btn(t("config.externalReload"), {
              variant: "primary",
              onClick: () => reloadSettings(),
            }),
            btn(t("common.dismiss"), {
              variant: "ghost",
              onClick: () => {
                localExternal = null;
                state.externalConfig = null;
                renderBanner();
              },
            })
          )
        )
      );
    }

    function renderWarnings() {
      clear(warningsHost);
      const warnings = (state.settingsMeta && state.settingsMeta.warnings) || [];
      const problems = (state.settingsMeta && state.settingsMeta.problems) || [];
      if (!warnings.length && !problems.length) return;
      const body = div("config-warnings");
      if (warnings.length) {
        body.appendChild(h("h3", { class: "warnings-title", text: t("config.warnings") }));
        const list = h("ul", { class: "warnings-list" });
        warnings.forEach((warning) => list.appendChild(h("li", { text: String(warning) })));
        body.appendChild(list);
      }
      if (problems.length) {
        body.appendChild(h("h3", { class: "warnings-title", text: t("config.problems") }));
        const list = h("ul", { class: "warnings-list" });
        const reasonLabels = {
          missing: t("config.problemMissing"),
          not_found: t("config.problemNotFound"),
          not_a_directory: t("config.problemNotDir"),
        };
        problems.forEach((problem) => {
          list.appendChild(
            h("li", {
              text: (problem.field || "") + ": " + (reasonLabels[problem.reason] || problem.reason || "") + (problem.value ? " — " + problem.value : ""),
            })
          );
        });
        body.appendChild(list);
      }
      warningsHost.appendChild(body);
    }

    function applyPathProblems() {
      const problems = (state.settingsMeta && state.settingsMeta.problems) || [];
      const mapping = {
        "audio.input_dir": "inputDir",
        "audio.output_dir": "outputDir",
        "audio.model_path": "modelPath",
        "audio.index_path": "indexPath",
      };
      const reasonLabels = {
        missing: t("config.problemMissing"),
        not_found: t("config.problemNotFound"),
        not_a_directory: t("config.problemNotDir"),
      };
      for (const [field, key] of Object.entries(mapping)) {
        if (fields && fields[key] && fields[key].setError) {
          const problem = problems.find((item) => item.field === field);
          fields[key].setError(problem ? reasonLabels[problem.reason] || t("config.problems") : "");
        }
      }
    }

    function buildForm() {
      const audio = (state.settings && state.settings.audio) || {};
      const draft = preservedDraft || draftFromSettings();
      clear(formHost);
      fields = {};

      const panel = div("config-grid");

      /* percorsi */
      fields.inputDir = pathField({
        id: "cfg-input-dir",
        label: t("config.inputDir"),
        value: draft.input_dir,
        hint: audio.input_dir ? "" : t("common.required"),
        kind: "directory",
        required: true,
        onChange: () => setDirty(true),
      });
      fields.outputDir = pathField({
        id: "cfg-output-dir",
        label: t("config.outputDir"),
        value: draft.output_dir,
        kind: "directory",
        onChange: () => setDirty(true),
      });
      fields.modelPath = pathField({
        id: "cfg-model",
        label: t("config.modelPath"),
        value: draft.model_path,
        kind: "model",
        required: true,
        onChange: () => setDirty(true),
      });
      fields.indexPath = pathField({
        id: "cfg-index",
        label: t("config.indexPath"),
        value: draft.index_path,
        hint: t("config.indexOptionalHint"),
        kind: "index",
        onChange: () => setDirty(true),
      });
      const pathsCard = card({
        title: t("config.sectionPaths"),
        children: [
          div("field-grid field-grid-paths", fields.inputDir.el, fields.outputDir.el, fields.modelPath.el, fields.indexPath.el),
          div(
            "button-row",
            btn(t("config.presetAndroid"), { variant: "secondary", iconName: "cloud", onClick: () => presetAndroid() })
          ),
        ],
      });

      /* voce */
      fields.pitch = rangeField({
        id: "cfg-pitch",
        label: t("config.pitch"),
        min: -24,
        max: 24,
        step: 1,
        value: draft.pitch,
        hint: t("config.pitchHint"),
        format: (value) => (value > 0 ? "+" + value : String(value)),
        onChange: () => setDirty(true),
      });
      fields.protect = rangeField({
        id: "cfg-protect",
        label: t("config.protect"),
        min: 0,
        max: 0.5,
        step: 0.01,
        value: draft.protect,
        hint: t("config.protectHint"),
        onChange: () => setDirty(true),
      });
      fields.indexRate = rangeField({
        id: "cfg-index-rate",
        label: t("config.indexRate"),
        min: 0,
        max: 1,
        step: 0.01,
        value: draft.index_rate,
        hint: t("config.indexRateHint"),
        onChange: () => setDirty(true),
      });
      fields.method = selectField({
        id: "cfg-method",
        label: t("config.method"),
        value: draft.method,
        options: METHODS,
        hint: t("config.methodHint"),
        onChange: () => setDirty(true),
      });
      const voiceCard = card({
        title: t("config.sectionVoice"),
        children: [
          fields.method.el,
          div("field-grid", fields.pitch.el, fields.protect.el, fields.indexRate.el),
        ],
      });

      /* esperti */
      fields.filterRadius = rangeField({
        id: "cfg-filter-radius",
        label: t("config.filterRadius"),
        min: 0,
        max: 7,
        step: 1,
        value: draft.filter_radius,
        hint: t("config.filterRadiusHint"),
        onChange: () => setDirty(true),
      });
      fields.rmsMixRate = rangeField({
        id: "cfg-rms",
        label: t("config.rmsMixRate"),
        min: 0,
        max: 1,
        step: 0.01,
        value: draft.rms_mix_rate,
        hint: t("config.rmsMixHint"),
        onChange: () => setDirty(true),
      });
      fields.resampleSr = rangeField({
        id: "cfg-resample",
        label: t("config.resampleSr"),
        min: 0,
        max: 48000,
        step: 1000,
        value: draft.resample_sr,
        hint: t("config.resampleHint"),
        onChange: () => setDirty(true),
      });
      fields.outputFormat = selectField({
        id: "cfg-format",
        label: t("config.outputFormat"),
        value: draft.output_format,
        options: OUTPUT_FORMATS,
        onChange: () => setDirty(true),
      });
      fields.modelVersion = selectField({
        id: "cfg-version",
        label: t("config.modelVersion"),
        value: draft.model_version,
        options: MODEL_VERSIONS,
        onChange: () => setDirty(true),
      });
      const expertBody = div("field-grid", fields.filterRadius.el, fields.rmsMixRate.el, fields.resampleSr.el);
      expertBody.append(div("field-grid", fields.outputFormat.el, fields.modelVersion.el));
      const expert = h(
        "details",
        { class: "expert", open: true },
        h("summary", { class: "expert-summary", text: t("config.sectionExpert") }),
        expertBody
      );
      const expertCard = card({ children: [expert] });

      panel.append(pathsCard, voiceCard, expertCard);
      formHost.appendChild(panel);
      applyPathProblems();
      preservedDraft = null;
      preservedDirty = false;
    }

    function renderEmpty(error) {
      clear(formHost);
      formHost.appendChild(
        emptyState({
          iconName: "alert",
          title: t("config.loadFailed"),
          text: t("config.loadFailedHint"),
          detail: error ? errorFull(error) : "",
          actions: [
            btn(t("common.retry"), {
              variant: "primary",
              iconName: "refresh",
              onClick: async () => {
                try {
                  await loadSettings();
                  buildForm();
                } catch (err) {
                  renderEmpty(err);
                }
              },
            }),
          ],
        })
      );
    }

    async function reloadSettings() {
      reloadButton.disabled = true;
      try {
        await loadSettings();
        localExternal = null;
        state.externalConfig = null;
        preservedDraft = null;
        setDirty(false);
        buildForm();
        renderWarnings();
        renderBanner();
        toast.success(t("common.reload"));
      } catch (err) {
        toast.error(err);
      } finally {
        reloadButton.disabled = false;
      }
    }

    async function save() {
      if (!fields) return;
      const draft = readDraft();
      saveButton.disabled = true;
      try {
        await patchSettings({ audio: draft });
        setDirty(false);
        preservedDirty = false;
        buildForm();
        renderWarnings();
        toast.success(t("config.saved"));
      } catch (err) {
        toast.error(err);
      } finally {
        saveButton.disabled = false;
      }
    }

    async function exportConfig() {
      exportButton.disabled = true;
      try {
        const blob = await endpoints.exportSettings();
        downloadBlob(blob, "rvc-portable-config.json");
        toast.success(t("config.exportDone"));
      } catch (err) {
        toast.error(err);
      } finally {
        exportButton.disabled = false;
      }
    }

    async function importConfig(file) {
      if (!file) return;
      importButton.disabled = true;
      try {
        const text = await file.text();
        let parsed;
        try {
          parsed = JSON.parse(text);
        } catch (err) {
          toast.error(t("common.invalidJson"));
          return;
        }
        const payload = parsed && parsed.settings && typeof parsed.settings === "object" ? parsed.settings : parsed;
        await endpoints.importSettings(payload);
        await loadSettings();
        preservedDraft = null;
        setDirty(false);
        buildForm();
        renderWarnings();
        toast.success(t("config.importDone"));
      } catch (err) {
        toast.show({ level: "error", message: t("config.importFailed"), detail: errorFull(err) });
      } finally {
        importButton.disabled = false;
        importInput.value = "";
      }
    }

    importInput.addEventListener("change", () => importConfig(importInput.files && importInput.files[0]));

    unsub = subscribe((reason) => {
      if (reason === "config-external") {
        renderBanner();
      } else if (reason === "settings") {
        renderWarnings();
        renderBanner();
      }
    });

    if (state.settings) {
      buildForm();
      renderWarnings();
      renderBanner();
    } else {
      renderEmpty(null);
    }

    configView.saveNow = save;

    return () => {
      if (unsub) unsub();
      configView.saveNow = null;
      if (dirty || preservedDraft) {
        preservedDraft = readDraft();
        preservedDirty = dirty;
      }
    };
  },

  onShortcut(key) {
    if (key === "save" && typeof configView.saveNow === "function") configView.saveNow();
  },
};
