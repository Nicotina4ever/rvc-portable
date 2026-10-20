/* RVC Portable — vista Avanzate: hardware, diagnostica, percorsi, preferenze. */
import { h, div, span, icon, clear, formatDateTime, formatMb } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { state, subscribe, setState } from "../core/store.js";
import { loadHardware, loadDiagnostics, loadEngineStatus } from "../core/data.js";
import { patchSettings } from "../core/settings.js";
import { applyTheme } from "../core/theme.js";
import { card, btn, badge, emptyState, kvRow, loadingBlock, statusBadge } from "../components/ui.js";
import { selectField } from "../components/fields.js";
import { confirmModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

function boolBadge(value) {
  if (value === true) return badge(t("common.yes"), "ok");
  if (value === false) return badge(t("common.no"), "neutral");
  return badge("—", "neutral");
}

function deviceOptions() {
  const options = [
    { value: "auto", label: t("advanced.deviceAuto") },
    { value: "cpu", label: t("advanced.deviceCpu") },
    { value: "cuda:0", label: t("advanced.deviceCuda") },
    { value: "mps", label: t("advanced.deviceMps") },
  ];
  const seen = new Set(options.map((item) => item.value));
  const hardware = state.hardware || {};
  for (const device of hardware.devices || []) {
    const value = String(device.device || device.id || device.value || "");
    if (!value || seen.has(value)) continue;
    seen.add(value);
    const unavailable = device.available === false;
    const label = String(device.label || device.name || value) + (unavailable ? " (" + t("common.notAvailable") + ")" : "");
    options.push({ value, label });
  }
  return options;
}

export const advancedView = {
  id: "advanced",
  titleKey: "nav.advanced",

  async mount(root, ctx, opts) {
    let unsub = null;
    let diagnosticsBusy = false;

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("advanced.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("advanced.subtitle") });
    const refreshButton = btn(t("common.refresh"), {
      variant: "ghost",
      iconName: "refresh",
      onClick: () => refreshAll(),
    });
    const header = div("view-header", div("view-heading", title, subtitle), div("view-actions", refreshButton));

    /* ------------------------------------------------------- hardware card */
    const hardwareBody = div("hardware-body");
    const hardwareCard = card({ title: t("advanced.hardware"), className: "advanced-card" });
    hardwareCard.body.appendChild(hardwareBody);

    /* ----------------------------------------------------- diagnostics card */
    const diagBody = div("diagnostics-body");
    const runDiagButton = btn(t("advanced.runDiagnostics"), { variant: "primary", iconName: "activity", onClick: () => runDiagnostics(true) });
    const diagCard = card({ title: t("advanced.diagnostics"), actions: runDiagButton, className: "advanced-card" });
    diagCard.body.appendChild(diagBody);

    /* ------------------------------------------------------- paths card */
    const pathsBody = div("paths-body");
    const pathsCard = card({ title: t("advanced.paths"), className: "advanced-card" });
    pathsCard.body.appendChild(pathsBody);

    /* -------------------------------------------------- preferences card */
    const preferencesBody = div("preferences-body");
    const preferencesCard = card({ title: t("advanced.preferences"), className: "advanced-card" });
    preferencesCard.body.appendChild(preferencesBody);

    /* --------------------------------------------------------- about card */
    const aboutBody = div("about-body");
    const aboutCard = card({ title: t("advanced.about"), className: "advanced-card" });
    aboutCard.body.appendChild(aboutBody);

    const layout = div(
      "advanced-layout",
      div("advanced-main", hardwareCard, diagCard),
      div("advanced-side", preferencesCard, pathsCard, aboutCard)
    );
    root.append(header, layout);

    function navigate(view, options) {
      if (ctx && ctx.navigate) ctx.navigate(view, options);
    }

    function probeRow(label, value) {
      return kvRow(label, value instanceof Node ? value : value === null || value === undefined || value === "" ? "—" : String(value));
    }

    function renderHardware() {
      clear(hardwareBody);
      if (state.hardwareError) {
        hardwareBody.appendChild(
          emptyState({
            iconName: "cpu",
            title: t("advanced.hardwareUnavailable"),
            text: t("advanced.hardwareUnavailableHint"),
            detail: errorFull(state.hardwareError),
            actions: [btn(t("common.retry"), { variant: "primary", iconName: "refresh", onClick: () => loadHardware() })],
          })
        );
        return;
      }
      const hardware = state.hardware;
      if (!hardware) {
        hardwareBody.appendChild(loadingBlock(t("common.loading")));
        return;
      }
      const probe = hardware.probe || {};
      const system = hardware.system || {};
      const devices = Array.isArray(hardware.devices) ? hardware.devices : [];

      hardwareBody.appendChild(h("h3", { class: "subsection-title", text: t("advanced.probe") }));
      const probeGrid = div(
        "kv-grid",
        probeRow(t("advanced.python"), probe.python_version || probe.python_executable || "—"),
        probeRow(t("advanced.torch"), probe.torch || "—"),
        probeRow(t("advanced.engineOk"), boolBadge(probe.engine_ok)),
        probeRow(t("advanced.fairseqOk"), boolBadge(probe.fairseq_ok)),
        probeRow(t("advanced.cudaAvailable"), boolBadge(Boolean(probe.cuda))),
        probeRow(t("advanced.mpsAvailable"), boolBadge(Boolean(probe.mps))),
        probeRow(t("advanced.gpuName"), probe.gpu_name || "—"),
        probeRow(t("advanced.vram"), probe.vram_gb !== null && probe.vram_gb !== undefined ? parseFloat(probe.vram_gb).toFixed(1) + " GB" : "—"),
        probeRow(t("advanced.checkedAt"), probe.checked_at ? formatDateTime(probe.checked_at) : "—"),
        probeRow(t("advanced.stale"), boolBadge(Boolean(probe.stale)))
      );
      hardwareBody.appendChild(probeGrid);
      if (probe.error) hardwareBody.appendChild(h("p", { class: "inline-warning", text: t("advanced.probeError") + ": " + probe.error }));

      hardwareBody.appendChild(h("h3", { class: "subsection-title", text: t("advanced.system") }));
      hardwareBody.appendChild(
        div(
          "kv-grid",
          probeRow(t("advanced.platform"), system.platform || "—"),
          probeRow(t("advanced.cpuCount"), system.cpu_count !== undefined ? String(system.cpu_count) : "—"),
          probeRow(t("advanced.ram"), system.ram_gb !== undefined ? String(system.ram_gb) + " GB" : "—"),
          probeRow(t("advanced.machine"), system.machine || "—")
        )
      );

      hardwareBody.appendChild(h("h3", { class: "subsection-title", text: t("advanced.devices") }));
      if (devices.length) {
        const list = h("ul", { class: "device-list" });
        for (const device of devices) {
          const value = device.device || device.id || device.value || "";
          list.appendChild(
            h(
              "li",
              { class: "device-item" },
              h("span", { class: "device-name", text: String(device.label || device.name || value) }),
              badge(device.available === false ? t("common.notAvailable") : t("common.on"), device.available === false ? "neutral" : "ok"),
              device.reason ? h("span", { class: "device-reason", text: String(device.reason) }) : null
            )
          );
        }
        hardwareBody.appendChild(list);
      }
      if (hardware.effective_device) {
        hardwareBody.appendChild(h("p", { class: "status-message", text: t("advanced.effectiveDevice", { device: hardware.effective_device }) }));
      }
      for (const warning of hardware.warnings || []) {
        hardwareBody.appendChild(h("p", { class: "inline-warning", text: String(warning) }));
      }

      const currentDevice = (state.settings && state.settings.engine && state.settings.engine.device) || "auto";
      const deviceSelect = selectField({
        id: "adv-device",
        label: t("advanced.deviceOverride"),
        value: currentDevice,
        options: deviceOptions(),
        hint: t("advanced.directmlNote"),
        onChange: (value) => saveDevice(value),
      });
      hardwareBody.appendChild(deviceSelect.el);
    }

    async function saveDevice(device) {
      try {
        await patchSettings({ engine: { device } });
        toast.success(t("advanced.deviceSaved", { device }));
      } catch (err) {
        toast.show({ level: "error", message: t("advanced.deviceSaveFailed"), detail: errorFull(err) });
      }
    }

    function renderDiagnostics() {
      clear(diagBody);
      runDiagButton.disabled = diagnosticsBusy;
      if (state.diagnosticsError) {
        diagBody.appendChild(
          emptyState({
            iconName: "activity",
            title: t("advanced.diagUnavailable"),
            text: t("advanced.diagUnavailableHint"),
            detail: errorFull(state.diagnosticsError),
            actions: [
              btn(t("common.retry"), { variant: "primary", iconName: "refresh", onClick: () => runDiagnostics(true) }),
            ],
          })
        );
        return;
      }
      const report = state.diagnostics;
      if (!report) {
        diagBody.appendChild(
          emptyState({
            iconName: "activity",
            title: t("advanced.diagnostics"),
            text: t("advanced.diagUnavailableHint"),
            actions: [btn(t("advanced.runDiagnostics"), { variant: "primary", iconName: "activity", onClick: () => runDiagnostics(true) })],
          })
        );
        return;
      }
      const overall = report.overall || "info";
      const overallLabel = overall === "ok" ? t("advanced.overallOk") : overall === "warn" ? t("advanced.overallWarn") : t("advanced.overallFail");
      const counts = report.counts || {};
      diagBody.appendChild(
        div(
          "diag-overall",
          statusBadge(overall === "ok" ? "ok" : overall === "warn" ? "warn" : "fail"),
          h("span", { class: "diag-overall-label", text: t("advanced.overall", { overall: overallLabel }) }),
          div(
            "diag-counts",
            badge(t("advanced.diagOk") + ": " + (counts.ok || 0), "ok"),
            badge(t("advanced.diagWarn") + ": " + (counts.warn || 0), "warn"),
            badge(t("advanced.diagFail") + ": " + (counts.fail || 0), "bad"),
            badge(t("advanced.diagInfo") + ": " + (counts.info || 0), "neutral")
          )
        )
      );
      const table = h("table", { class: "diag-table" });
      table.appendChild(
        h(
          "thead",
          null,
          h("tr", null, h("th", { text: t("advanced.check") }), h("th", { text: t("common.status") }), h("th", { text: t("advanced.detail") }))
        )
      );
      const tbody = h("tbody");
      for (const check of report.checks || []) {
        const kind = check.status === "ok" ? "ok" : check.status === "warn" ? "warn" : check.status === "fail" ? "fail" : "info";
        const row = h(
          "tr",
          { class: "diag-row diag-row-" + kind },
          h("td", { class: "diag-label", text: String(check.label || check.id || "") }),
          h("td", null, statusBadge(kind)),
          h(
            "td",
            { class: "diag-detail-cell" },
            h("span", { class: "diag-detail", text: check.detail || "" }),
            check.fix ? h("span", { class: "diag-fix", text: t("advanced.fix") + ": " + check.fix }) : null
          )
        );
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      diagBody.appendChild(table);
    }

    async function runDiagnostics(force) {
      if (diagnosticsBusy) return;
      diagnosticsBusy = true;
      runDiagButton.disabled = true;
      const label = runDiagButton.querySelector(".btn-label");
      if (label) label.textContent = t("advanced.runningDiagnostics");
      try {
        await loadDiagnostics(force !== false);
      } finally {
        diagnosticsBusy = false;
        runDiagButton.disabled = false;
        if (label) label.textContent = t("advanced.runDiagnostics");
        renderDiagnostics();
      }
    }

    function getMetaPaths() {
      const meta = state.meta || {};
      return meta.paths || (state.settingsMeta && state.settingsMeta.config_path ? { config_path: state.settingsMeta.config_path } : {});
    }

    function pathRow(label, target, value) {
      const button = btn(t("advanced.reveal"), {
        variant: "ghost",
        iconName: "folder",
        className: "btn-sm",
        onClick: () => revealPath(target),
      });
      return div("path-row-item", div("path-row-text", h("span", { class: "path-label", text: label }), h("span", { class: "path-value", title: value || "", text: value || "—" })), button);
    }

    function renderPaths() {
      clear(pathsBody);
      const paths = getMetaPaths();
      pathsBody.append(
        pathRow(t("advanced.configPath"), "config", paths.config_path || (state.settingsMeta && state.settingsMeta.config_path) || ""),
        pathRow(t("advanced.logsDir"), "logs", paths.logs_dir || ""),
        pathRow(t("advanced.dataDir"), "data", paths.data_dir || ""),
        pathRow(t("advanced.cacheDir"), "cache", paths.cache_dir || "")
      );
    }

    async function revealPath(target) {
      try {
        const result = await endpoints.reveal(target);
        toast.success(t("advanced.revealed", { path: (result && result.path) || "" }));
      } catch (err) {
        toast.show({ level: "error", message: t("advanced.revealFailed"), detail: errorFull(err) });
      }
    }

    function renderPreferences() {
      clear(preferencesBody);
      const ui = (state.settings && state.settings.ui) || {};
      const languageSelect = selectField({
        id: "adv-language",
        label: t("advanced.language"),
        value: state.lang || ui.language || "it",
        options: [
          { value: "it", label: "Italiano" },
          { value: "en", label: "English" },
        ],
        onChange: (value) => changeLanguage(value),
      });
      const themeSelect = selectField({
        id: "adv-theme",
        label: t("advanced.theme"),
        value: state.theme || ui.theme || "dark",
        options: [
          { value: "dark", label: t("advanced.themeDark") },
          { value: "light", label: t("advanced.themeLight") },
          { value: "system", label: t("advanced.themeSystem") },
        ],
        onChange: (value) => changeTheme(value),
      });
      preferencesBody.append(languageSelect.el, themeSelect.el);
    }

    async function changeLanguage(code) {
      try {
        if (ctx && ctx.setLanguage) await ctx.setLanguage(code);
        else await patchSettings({ ui: { language: code } });
        toast.success(t("advanced.languageSaved"));
      } catch (err) {
        toast.error(err);
      }
    }

    async function changeTheme(theme) {
      applyTheme(theme);
      try {
        await patchSettings({ ui: { theme } });
        toast.success(t("advanced.themeSaved"));
      } catch (err) {
        toast.error(err);
      }
    }

    function renderAbout() {
      clear(aboutBody);
      const meta = state.meta || {};
      const version = meta.version || state.version || "3.0.0";
      const platform = meta.platform || (state.health && state.health.platform) || navigator.platform || "—";
      const python = meta.python || (meta.engine && meta.engine.extra && meta.engine.extra.python) || "—";
      aboutBody.append(
        kvRow(t("advanced.version"), String(version)),
        kvRow(t("advanced.platform"), String(platform)),
        kvRow(t("advanced.python"), String(python)),
        kvRow(t("advanced.credits"), t("advanced.creditsValue")),
        h("p", { class: "about-credits", text: t("advanced.creditsValue") }),
        div(
          "button-row",
          btn(t("common.refresh"), { variant: "secondary", iconName: "refresh", onClick: () => refreshAll() }),
          btn(t("advanced.shutdown"), { variant: "danger", iconName: "power", onClick: () => shutdown() })
        )
      );
    }

    async function shutdown() {
      const confirmed = await confirmModal({
        title: t("advanced.shutdownTitle"),
        message: t("advanced.shutdownText"),
        confirmLabel: t("advanced.shutdownConfirm"),
        danger: true,
      });
      if (!confirmed) return;
      try {
        await endpoints.shutdown();
        toast.success(t("advanced.shutdownOk"));
        clear(root);
        root.appendChild(
          emptyState({
            iconName: "power",
            title: t("advanced.shutdownOk"),
            text: t("app.serverOffline"),
          })
        );
      } catch (err) {
        toast.show({ level: "error", message: t("advanced.shutdownFailed"), detail: errorFull(err) });
      }
    }

    async function refreshAll() {
      refreshButton.disabled = true;
      try {
        await Promise.allSettled([loadEngineStatus(), loadHardware()]);
        renderPreferences();
        renderPaths();
        renderAbout();
      } finally {
        refreshButton.disabled = false;
      }
    }

    unsub = subscribe((reason) => {
      if (reason === "hardware") renderHardware();
      else if (reason === "diagnostics") renderDiagnostics();
      else if (reason === "settings" || reason === "engine" || reason === "meta") {
        renderPreferences();
        renderPaths();
        renderAbout();
        if (reason === "settings") renderHardware();
      } else if (reason === "theme") {
        renderPreferences();
      }
    });

    renderHardware();
    renderDiagnostics();
    renderPaths();
    renderPreferences();
    renderAbout();

    await Promise.allSettled([loadEngineStatus(), loadHardware()]);
    if (opts && opts.runDiagnostics) runDiagnostics(true);

    return () => {
      if (unsub) unsub();
    };
  },
};
