/* RVC Portable — vista Modelli: scansione, gruppi, attivazione. */
import { h, div, span, icon, clear, basename, dirname, formatMb, timeAgo, truncateMiddle } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { state, subscribe } from "../core/store.js";
import { loadModels } from "../core/data.js";
import { patchSettings } from "../core/settings.js";
import { card, btn, badge, emptyState, loadingBlock } from "../components/ui.js";
import { searchField } from "../components/fields.js";
import { toast } from "../components/toast.js";

function isMismatch(model) {
  return (model.warnings || []).some((warning) => /mismatch/i.test(String(warning)));
}

export const modelsView = {
  id: "models",
  titleKey: "nav.models",

  async mount(root, ctx) {
    let unsub = null;
    let query = "";
    let applying = false;

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("models.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("models.subtitle") });
    const search = searchField({
      placeholder: t("models.searchPlaceholder"),
      onInput: (value) => {
        query = String(value || "").toLowerCase();
        renderModels();
      },
    });
    const refreshButton = btn(t("models.refresh"), { variant: "secondary", iconName: "refresh" });
    const rescanButton = btn(t("models.rescan"), { variant: "secondary", iconName: "search" });
    const header = div(
      "view-header",
      div("view-heading", title, subtitle),
      div("view-actions", search, rescanButton, refreshButton)
    );

    const summaryHost = div("models-summary");
    const warningsHost = div("warnings-host");
    const listHost = div("models-list");
    root.append(header, summaryHost, warningsHost, listHost);

    function currentModelPath() {
      return ((state.settings && state.settings.audio && state.settings.audio.model_path) || "").toLowerCase();
    }

    function renderSummary() {
      clear(summaryHost);
      const data = state.models;
      if (!data) return;
      const roots = data.roots || [];
      if (roots.length) {
        summaryHost.appendChild(
          h(
            "p",
            { class: "models-roots" },
            span("models-roots-label", t("models.roots") + ": "),
            ...roots.map((root, index) => span("models-root", (index ? " · " : "") + root))
          )
        );
      }
      summaryHost.appendChild(h("p", { class: "models-count", text: t("models.count", { count: (data.models || []).length }) }));
    }

    function renderWarnings() {
      clear(warningsHost);
      const data = state.models;
      if (!data || !data.warnings || !data.warnings.length) return;
      warningsHost.appendChild(
        h(
          "div",
          { class: "inline-warning" },
          icon("alert"),
          span("", data.warnings.join(" · "))
        )
      );
    }

    function modelCard(model) {
      const inUse = Boolean(model.path) && currentModelPath() === String(model.path).toLowerCase();
      const version = model.version_guess || "v2";
      const warnings = model.warnings || [];
      const headerRow = div(
        "model-head",
        div(
          "model-title",
          h("h3", { class: "model-name", title: model.path || "", text: model.name || basename(model.path) || "—" }),
          div("model-badges", badge(version, "info"), model.has_index ? badge(t("models.indexOk"), "ok") : badge(t("models.indexMissing"), "warn"))
        ),
        inUse ? badge(t("models.inUse"), "ok") : null
      );
      const body = div("model-body", h("p", { class: "model-path", title: model.path || "", text: truncateMiddle(model.path || "", 68) }));
      body.appendChild(
        div(
          "model-meta",
          span("model-meta-item", t("models.size", { size: formatMb(model.size_mb) })),
          model.mtime ? span("model-meta-item", t("models.modified", { time: timeAgo(model.mtime) })) : null,
          model.source ? span("model-meta-item", t("models.source") + ": " + model.source) : null
        )
      );
      if (isMismatch(model)) {
        body.appendChild(h("p", { class: "model-warning" }, icon("alert"), span("", t("models.mismatch"))));
      }
      if (warnings.length) {
        const list = h("ul", { class: "model-warnings" });
        warnings.forEach((warning) => list.appendChild(h("li", { text: String(warning) })));
        body.appendChild(list);
      }
      const useButton = btn(inUse ? t("models.inUse") : t("models.use"), {
        variant: inUse ? "secondary" : "primary",
        iconName: inUse ? "check" : "play",
        onClick: () => applyModel(model),
      });
      useButton.disabled = inUse || applying;
      body.appendChild(div("model-actions", useButton));
      return div("model-card" + (inUse ? " is-active" : ""), headerRow, body);
    }

    function renderModels() {
      clear(listHost);
      if (state.modelsError) {
        listHost.appendChild(
          emptyState({
            iconName: "alert",
            title: t("models.unavailable"),
            text: t("models.unavailableHint"),
            detail: errorFull(state.modelsError),
            actions: [
              btn(t("common.retry"), { variant: "primary", iconName: "refresh", onClick: () => refresh(true) }),
            ],
          })
        );
        return;
      }
      const data = state.models;
      if (!data) {
        listHost.appendChild(loadingBlock(t("models.loading")));
        return;
      }
      const models = (data.models || []).filter((model) => {
        if (!query) return true;
        return (
          String(model.name || "").toLowerCase().includes(query) ||
          String(model.path || "").toLowerCase().includes(query)
        );
      });
      if (!models.length) {
        listHost.appendChild(
          emptyState({
            iconName: "layers",
            title: data.models && data.models.length ? t("models.noMatch") : t("models.empty"),
            text: data.models && data.models.length ? "" : t("models.emptyHint"),
          })
        );
        return;
      }
      const groups = new Map();
      for (const model of models) {
        const key = model.source || dirname(model.path || "") || t("common.unknown");
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(model);
      }
      for (const [group, entries] of groups) {
        const groupNode = div(
          "model-group",
          div("model-group-head", h("h2", { class: "model-group-title", text: group }), badge(String(entries.length), "neutral")),
          div("model-grid", entries.map((model) => modelCard(model)))
        );
        listHost.appendChild(groupNode);
      }
    }

    async function applyModel(model) {
      if (applying) return;
      applying = true;
      renderModels();
      try {
        await patchSettings({
          audio: {
            model_path: model.path || "",
            index_path: model.index_path || "",
          },
        });
        toast.success(t("models.applied", { name: model.name || basename(model.path) || "" }));
      } catch (err) {
        toast.show({ level: "error", message: t("models.applyFailed"), detail: errorFull(err) });
      } finally {
        applying = false;
        renderModels();
      }
    }

    async function refresh(rescan) {
      refreshButton.disabled = true;
      rescanButton.disabled = true;
      try {
        await loadModels({ rescan: Boolean(rescan) });
      } finally {
        refreshButton.disabled = false;
        rescanButton.disabled = false;
      }
    }

    refreshButton.addEventListener("click", () => refresh(false));
    rescanButton.addEventListener("click", () => refresh(true));

    unsub = subscribe((reason) => {
      if (reason === "models") {
        renderSummary();
        renderWarnings();
        renderModels();
      } else if (reason === "settings") {
        renderModels();
      }
    });

    renderModels();
    await loadModels();

    return () => {
      if (unsub) unsub();
    };
  },
};
