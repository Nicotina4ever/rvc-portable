/* RVC Portable — vista Monitor: watcher, log live e filtri. */
import { h, div, span, icon, clear, appendAll, formatClock } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { state, subscribe } from "../core/store.js";
import { loadMonitor } from "../core/data.js";
import { patchSettings } from "../core/settings.js";
import { card, btn, badge, emptyState } from "../components/ui.js";
import { pathField, switchField, selectField } from "../components/fields.js";
import { toast } from "../components/toast.js";

const LEVEL_RANK = { debug: 10, info: 20, warning: 30, warn: 30, error: 40, critical: 50 };
const LEVEL_LABEL = { debug: "DEBUG", info: "INFO", warning: "WARN", warn: "WARN", error: "ERROR", critical: "CRIT" };

function levelRank(level) {
  return LEVEL_RANK[String(level || "info").toLowerCase()] || 20;
}

export const monitorView = {
  id: "monitor",
  titleKey: "nav.monitor",

  async mount(root, ctx) {
    let unsub = null;
    let logIndex = 0;
    let filterLevel = "info";
    let autoscroll = true;
    let busy = false;

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("monitor.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("monitor.subtitle") });
    const refreshButton = btn(t("common.refresh"), { variant: "ghost", iconName: "refresh" });
    const header = div("view-header", div("view-heading", title, subtitle), div("view-actions", refreshButton));

    /* ---------------------------------------------------------- status card */
    const statusBody = div("monitor-status");
    const statusCard = card({ title: t("monitor.status"), className: "monitor-card" });
    statusCard.body.appendChild(statusBody);

    /* ------------------------------------------------------- controls card */
    const dirField = pathField({
      id: "mon-dir",
      label: t("monitor.dir"),
      value: (state.settings && state.settings.audio && state.settings.audio.input_dir) || "",
      kind: "directory",
      hint: t("monitor.hint"),
    });
    const processExistingSwitch = switchField({
      id: "mon-existing",
      label: t("monitor.processExisting"),
      checked: Boolean(state.settings && state.settings.monitor && state.settings.monitor.process_existing),
      hint: t("monitor.processExistingHint"),
    });
    const startButton = btn(t("monitor.start"), { variant: "primary", iconName: "play" });
    const stopButton = btn(t("monitor.stop"), { variant: "secondary", iconName: "stop" });
    const processButton = btn(t("monitor.processExisting"), { variant: "secondary", iconName: "inbox" });
    const controlsBody = div("monitor-controls");
    controlsBody.append(dirField.el, processExistingSwitch.el, div("button-row", startButton, stopButton, processButton));
    const controlsCard = card({ title: t("monitor.title"), className: "monitor-card" });
    controlsCard.body.appendChild(controlsBody);
    const controlAlert = div("inline-alert", { hidden: true });
    controlsCard.body.appendChild(controlAlert);

    /* ------------------------------------------------------------- log card */
    const levelSelect = selectField({
      id: "mon-level",
      label: t("monitor.level"),
      value: filterLevel,
      options: [
        { value: "debug", label: "DEBUG" },
        { value: "info", label: "INFO" },
        { value: "warning", label: "WARN" },
        { value: "error", label: "ERROR" },
      ],
    });
    const autoscrollSwitch = switchField({
      id: "mon-autoscroll",
      label: t("monitor.autoscroll"),
      checked: autoscroll,
    });
    const clearButton = btn(t("monitor.clearLog"), { variant: "ghost", iconName: "trash" });
    const toolbar = div("log-toolbar", levelSelect.el, autoscrollSwitch.el, clearButton);
    const logList = h("ul", {
      class: "log-list",
      role: "log",
      "aria-live": "polite",
      "aria-label": t("monitor.log"),
    });
    const logEmpty = h("p", { class: "log-empty", text: t("monitor.logEmpty") });
    const logBody = div("log-body", logList, logEmpty);
    const logCard = card({ title: t("monitor.log"), actions: toolbar, className: "log-card" });
    logCard.body.appendChild(logBody);

    const layout = div("monitor-layout", div("monitor-main", controlsCard, logCard), statusCard);
    root.append(header, layout);

    /* ---------------------------------------------------------------- log */
    function appendLine(entry) {
      const level = String(entry.level || "info").toLowerCase();
      const node = h(
        "li",
        { class: "log-line log-" + (LEVEL_LABEL[level] ? level : "info") },
        h("time", { class: "log-time", text: formatClock(entry.ts) }),
        span("log-level", LEVEL_LABEL[level] || "INFO"),
        span("log-source", entry.source || "app"),
        span("log-message", entry.message || "")
      );
      logList.appendChild(node);
      while (logList.children.length > 500) logList.firstElementChild.remove();
    }

    function trimDom() {
      while (logList.children.length > 500) logList.firstElementChild.remove();
    }

    function appendNewLogs() {
      if (logIndex > state.logs.length) {
        rebuildLogs();
        return;
      }
      const threshold = levelRank(filterLevel);
      for (; logIndex < state.logs.length; logIndex += 1) {
        const entry = state.logs[logIndex];
        if (levelRank(entry.level) < threshold) continue;
        appendLine(entry);
      }
      trimDom();
      const hasLines = logList.children.length > 0;
      logEmpty.hidden = hasLines;
      if (autoscroll && hasLines) logBody.scrollTop = logBody.scrollHeight;
    }

    function rebuildLogs() {
      clear(logList);
      logIndex = 0;
      appendNewLogs();
    }

    /* ------------------------------------------------------------- status */
    function modeLabel(mode) {
      const map = {
        auto: t("monitor.modeAuto"),
        native: t("monitor.modeNative"),
        polling: t("monitor.modePolling"),
        none: t("monitor.modeNone"),
      };
      return map[mode] || mode || "";
    }

    function renderStatus() {
      clear(statusBody);
      const monitor = state.monitor || {};
      if (state.monitorError) {
        statusBody.appendChild(
          emptyState({
            iconName: "alert",
            title: t("monitor.unavailable"),
            text: t("monitor.unavailableHint"),
            detail: state.monitorError.message || "",
          })
        );
        return;
      }
      const running = Boolean(monitor.running);
      appendAll(
        statusBody,
        div(
          "status-row",
          span("status-dot dot-" + (running ? "ok" : "neutral")),
          span("status-value", running ? t("monitor.running") : t("monitor.stopped")),
          running && monitor.mode ? badge(modeLabel(monitor.mode), "accent") : null
        ),
        div(
          "status-stats",
          div("status-stat", span("stat-value", String(monitor.processed_session || 0)), span("stat-label", t("monitor.processedLabel"))),
          div("status-stat", span("stat-value", String(monitor.queued || 0)), span("stat-label", t("monitor.queuedLabel")))
        ),
        h("p", { class: "status-message", title: monitor.dir || "", text: monitor.dir ? t("monitor.dir") + ": " + monitor.dir : t("monitor.dir") + ": —" })
      );
    }

    function renderControls() {
      const monitor = state.monitor || {};
      const running = Boolean(monitor.running);
      const available = !state.monitorError;
      startButton.disabled = busy || running || !available;
      stopButton.disabled = busy || !running || !available;
      processButton.disabled = busy || !available;
      startButton.hidden = running;
      stopButton.hidden = !running;
      if (state.monitorError) {
        controlAlert.hidden = false;
        controlAlert.textContent = t("monitor.unavailableHint");
      } else {
        controlAlert.hidden = true;
        controlAlert.textContent = "";
      }
      if (!dirField.getValue() && monitor.dir) dirField.setValue(monitor.dir);
    }

    async function withBusy(button, labelBusy, action) {
      if (busy) return;
      busy = true;
      renderControls();
      const labelNode = button.querySelector(".btn-label");
      const labelIdle = labelNode ? labelNode.textContent : "";
      if (labelNode) labelNode.textContent = labelBusy;
      try {
        await action();
      } finally {
        busy = false;
        if (labelNode) labelNode.textContent = labelIdle;
        renderControls();
      }
    }

    async function startMonitor() {
      const directory = dirField.getValue().trim();
      if (!directory) {
        toast.warning(t("monitor.dirRequired"));
        return;
      }
      const processExisting = processExistingSwitch.getValue();
      await withBusy(startButton, t("monitor.starting"), async () => {
        try {
          await endpoints.monitorStart({ dir: directory, process_existing: processExisting });
          await loadMonitor({ silent: true });
          toast.success(t("monitor.startOk"));
          const audio = (state.settings && state.settings.audio) || {};
          if (audio.input_dir !== directory) {
            await patchSettings({ audio: { input_dir: directory } }).catch(() => null);
          }
          if (processExisting) await processExistingFiles(directory, true);
        } catch (err) {
          toast.error(err);
        }
      });
    }

    async function stopMonitor() {
      await withBusy(stopButton, t("monitor.stopping"), async () => {
        try {
          await endpoints.monitorStop();
          await loadMonitor({ silent: true });
          toast.success(t("monitor.stopOk"));
        } catch (err) {
          toast.error(err);
        }
      });
    }

    async function processExistingFiles(directory, quiet) {
      const target = (directory || dirField.getValue() || "").trim();
      if (!target) {
        if (!quiet) toast.warning(t("monitor.dirRequired"));
        return;
      }
      try {
        const result = await endpoints.monitorProcessExisting({ dir: target });
        const count = Number((result && result.enqueued) || 0);
        if (count > 0) toast.success(t("monitor.processExistingOk", { count }));
        else toast.info(t("monitor.processExistingNone"));
        await loadMonitor({ silent: true });
      } catch (err) {
        if (!quiet) toast.error(err);
      }
    }

    async function refresh() {
      refreshButton.disabled = true;
      try {
        await loadMonitor();
      } finally {
        refreshButton.disabled = false;
      }
    }

    /* --------------------------------------------------------------- events */
    startButton.addEventListener("click", startMonitor);
    stopButton.addEventListener("click", stopMonitor);
    processButton.addEventListener("click", () => processExistingFiles());
    refreshButton.addEventListener("click", refresh);
    levelSelect.select.addEventListener("change", () => {
      filterLevel = levelSelect.getValue();
      rebuildLogs();
    });
    autoscrollSwitch.input.addEventListener("change", () => {
      autoscroll = autoscrollSwitch.getValue();
      if (autoscroll) logBody.scrollTop = logBody.scrollHeight;
    });
    clearButton.addEventListener("click", () => {
      state.logs.length = 0;
      logIndex = 0;
      rebuildLogs();
    });

    unsub = subscribe((reason) => {
      if (reason === "monitor") {
        renderStatus();
        renderControls();
      } else if (reason === "log") {
        appendNewLogs();
      } else if (reason === "settings" || reason === "jobs") {
        renderControls();
      }
    });

    renderStatus();
    renderControls();
    rebuildLogs();
    await loadMonitor();

    monitorView.toggle = async () => {
      if (busy) return;
      if (state.monitor && state.monitor.running) await stopMonitor();
      else await startMonitor();
    };

    return () => {
      if (unsub) unsub();
      monitorView.toggle = null;
    };
  },

  async onShortcut(key) {
    if (key === "toggle-monitor" && typeof monitorView.toggle === "function") await monitorView.toggle();
  },
};
