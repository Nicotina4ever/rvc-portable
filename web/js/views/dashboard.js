/* RVC Portable — vista Dashboard: stato, accodamento, coda, risultati. */
import {
  h,
  div,
  span,
  icon,
  clear,
  appendAll,
  basename,
  truncateMiddle,
  formatDuration,
  formatMb,
  timeAgo,
} from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { state, subscribe } from "../core/store.js";
import {
  engineSnapshot,
  loadJobs,
  loadMonitor,
  loadEngineStatus,
  loadHardware,
  loadHealth,
} from "../core/data.js";
import { card, btn, badge, emptyState, kvRow, statusBadge } from "../components/ui.js";
import { createJobBoard } from "../components/jobboard.js";
import { toast } from "../components/toast.js";

function statusVariant(available) {
  if (available === true) return "ok";
  if (available === false) return "bad";
  return "neutral";
}

export const dashboardView = {
  id: "dashboard",
  titleKey: "nav.dashboard",

  async mount(root, ctx) {
    let unsub = null;
    let board = null;

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("dashboard.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("dashboard.subtitle") });
    const refreshButton = btn(t("common.refresh"), { variant: "ghost", iconName: "refresh" });

    const header = div(
      "view-header",
      div("view-heading", title, subtitle),
      div("view-actions", refreshButton)
    );

    /* ------------------------------------------------------- status cards */
    const engineCard = card({ title: t("dashboard.engine"), subtitle: t("dashboard.engineHint"), className: "status-card" });
    const modelCard = card({ title: t("dashboard.model"), subtitle: t("dashboard.modelHint"), className: "status-card" });
    const vramCard = card({ title: t("dashboard.vram"), subtitle: t("dashboard.vramHint"), className: "status-card" });
    const statusGrid = div("status-grid", engineCard, modelCard, vramCard);

    /* ---------------------------------------------------------- drop zone */
    const filePathInput = h("input", {
      class: "input input-mono",
      type: "text",
      placeholder: t("dashboard.manualPathPlaceholder"),
      "aria-label": t("dashboard.manualPath"),
      autocomplete: "off",
      spellcheck: "false",
    });
    const browseButton = btn(t("dashboard.browseFile"), { variant: "primary", iconName: "folder" });
    const enqueueButton = btn(t("dashboard.enqueue"), { variant: "secondary", iconName: "play" });
    const dropZone = div(
      "dropzone",
      span("dropzone-icon", icon("file-audio")),
      h("h3", { class: "dropzone-title", text: t("dashboard.dropTitle") }),
      h("p", { class: "dropzone-hint", text: t("dashboard.dropHint") }),
      div("dropzone-actions", browseButton)
    );
    dropZone.setAttribute("role", "group");
    dropZone.setAttribute("aria-label", t("dashboard.dropTitle"));
    const manualRow = div("manual-path", filePathInput, enqueueButton);
    const configWarnings = div("inline-warnings");
    const dropCard = card({
      title: t("dashboard.newConversion"),
      className: "drop-card",
      children: [dropZone, manualRow, configWarnings],
    });

    /* ------------------------------------------------------- queue card */
    const statsHost = div("stats-badges");
    const clearButton = btn(t("dashboard.quickClear"), { variant: "ghost", iconName: "trash", className: "btn-sm" });
    const queueCard = card({
      title: t("dashboard.queue"),
      actions: [statsHost, clearButton],
      className: "queue-card",
    });
    board = createJobBoard();
    queueCard.body.appendChild(board.el);

    /* ------------------------------------------------------- aside cards */
    const recentBody = div("recent-list");
    const recentCard = card({ title: t("dashboard.recent") });
    recentCard.body.appendChild(recentBody);

    const quickBody = div("quick-actions");
    const quickCard = card({ title: t("dashboard.quickActions") });
    quickCard.body.appendChild(quickBody);

    const mainColumn = div("dashboard-main", dropCard, queueCard);
    const asideColumn = div("dashboard-aside", recentCard, quickCard);
    const layout = div("dashboard-layout", mainColumn, asideColumn);

    root.append(header, statusGrid, layout);

    /* ---------------------------------------------------------- helpers */
    let monitorBusy = false;

    function navigate(view, options) {
      if (ctx && ctx.navigate) ctx.navigate(view, options);
    }

    function renderStatusCards() {
      const engine = engineSnapshot();
      const audio = (state.settings && state.settings.audio) || {};
      const hardware = state.hardware || {};
      const probe = hardware.probe || {};

      /* motore */
      clear(engineCard.body);
      const engineAvailable = engine ? Boolean(engine.available) : null;
      appendAll(
        engineCard.body,
        div(
          "status-row",
          span("status-dot dot-" + statusVariant(engineAvailable)),
          span("status-value", engine ? t(engineAvailable ? "engine.available" : "engine.unavailable") : t("engine.unknown"))
        ),
        kvRow(t("advanced.deviceOverride"), (engine && (engine.device || engine.requested_device)) || (state.settings && state.settings.engine && state.settings.engine.device) || "—"),
        kvRow(t("dashboard.model"), audio.model_path ? basename(audio.model_path) : t("dashboard.noModel")),
        engine && engine.loaded ? div("status-tags", badge(t("engine.loaded"), "ok"), engine.warm ? badge(t("engine.warm"), "info") : null) : null,
        engine && engine.busy ? badge(t("engine.busy"), "warn") : null,
        engine && engine.message ? h("p", { class: "status-message", text: engine.message }) : null,
        engineAvailable === false ? h("p", { class: "status-hint", text: t("dashboard.engineDownHint") }) : null
      );

      /* modello */
      clear(modelCard.body);
      modelCard.body.append(
        kvRow(t("common.name"), audio.model_path ? basename(audio.model_path) : t("dashboard.noModel")),
        kvRow(t("common.path"), audio.model_path ? truncateMiddle(audio.model_path, 44) : "—"),
        kvRow(t("common.version"), audio.model_version || "v2"),
        div(
          "status-tags",
          audio.index_path ? badge(t("models.indexOk"), "ok") : badge(t("models.indexMissing"), "warn"),
          audio.input_dir ? badge(t("dashboard.inputConfigured"), "info") : badge(t("dashboard.noInput"), "warn")
        )
      );

      /* VRAM */
      clear(vramCard.body);
      if (state.hardwareError) {
        vramCard.body.append(
          h("p", { class: "status-message", text: t("dashboard.vramUnavailable") }),
          h("p", { class: "status-hint", text: t("advanced.hardwareUnavailableHint") })
        );
      } else {
        const vram = probe.vram_gb;
        vramCard.body.append(
          kvRow(t("advanced.vram"), vram !== null && vram !== undefined ? parseFloat(vram).toFixed(1) + " GB" : "—"),
          kvRow(t("advanced.gpuName"), probe.gpu_name || "—"),
          div(
            "status-tags",
            badge(probe.cuda ? t("advanced.cudaAvailable") : t("advanced.cpuOnly"), probe.cuda ? "ok" : "neutral"),
            probe.mps ? badge(t("advanced.mpsAvailable"), "ok") : null
          )
        );
      }

      /* avvisi configurazione */
      clear(configWarnings);
      const warnings = [];
      if (!audio.model_path) warnings.push(t("dashboard.noModel"));
      if (!audio.input_dir) warnings.push(t("dashboard.noInput"));
      if (state.settingsLoaded && !(audio.output_dir || "")) warnings.push(t("errors.output_dir_missing"));
      if (warnings.length) {
        configWarnings.appendChild(
          h(
            "p",
            { class: "inline-warning" },
            icon("alert"),
            span("", warnings.join(" · ") + " — " + t("dashboard.engineDisabled"))
          )
        );
      }
    }

    function renderStats() {
      clear(statsHost);
      const stats = state.stats || {};
      const entries = [
        ["queued", t("job.stateQueued")],
        ["running", t("job.stateRunning")],
        ["done", t("job.stateDone")],
        ["failed", t("job.stateFailed")],
      ];
      for (const [key, label] of entries) {
        const value = Number(stats[key] || 0);
        if (!value) continue;
        statsHost.appendChild(badge(label + ": " + value, key === "failed" ? "bad" : key === "done" ? "ok" : "info"));
      }
    }

    function renderRecent() {
      clear(recentBody);
      const done = state.jobs
        .filter((job) => job.state === "done")
        .sort((left, right) => (right.finished_at || 0) - (left.finished_at || 0))
        .slice(0, 5);
      if (!done.length) {
        recentBody.appendChild(
          emptyState({
            iconName: "wave",
            title: t("dashboard.recentEmpty"),
            text: t("dashboard.recentEmptyHint"),
          })
        );
        return;
      }
      for (const job of done) {
        const duration = job.duration_s ? t("dashboard.duration", { time: formatDuration(job.duration_s) }) : "";
        const row = div(
          "recent-row",
          span("recent-icon", icon("file-audio")),
          div(
            "recent-text",
            h("p", { class: "recent-name", title: job.input_path || "", text: job.output_name || job.basename || "—" }),
            h("p", { class: "recent-meta", text: [duration, job.finished_at ? timeAgo(job.finished_at) : ""].filter(Boolean).join(" · ") })
          )
        );
        if (job.output_path) {
          row.appendChild(
            h(
              "a",
              {
                class: "btn btn-ghost btn-icon",
                href: endpoints.audioUrl(job.id, "output"),
                download: job.output_name || "output.wav",
                title: t("dashboard.download"),
                "aria-label": t("dashboard.download"),
              },
              icon("download")
            )
          );
        }
        recentBody.appendChild(row);
      }
    }

    function renderQuickActions() {
      clear(quickBody);
      const monitor = state.monitor || {};
      const monitorButton = monitor.running
        ? btn(t("dashboard.quickStopMonitor"), { variant: "secondary", iconName: "stop", onClick: () => toggleMonitor(false) })
        : btn(t("dashboard.quickStartMonitor"), { variant: "primary", iconName: "play", onClick: () => toggleMonitor(true) });
      monitorButton.disabled = monitorBusy;
      quickBody.append(
        monitorButton,
        btn(t("dashboard.quickConfig"), { variant: "secondary", iconName: "sliders", onClick: () => navigate("config") }),
        btn(t("dashboard.quickDiagnostics"), { variant: "secondary", iconName: "activity", onClick: () => navigate("advanced", { runDiagnostics: true }) }),
        btn(t("dashboard.quickClear"), { variant: "ghost", iconName: "trash", onClick: clearFinished })
      );
    }

    function setBusy(button, busy, labelBusy, labelIdle) {
      button.disabled = busy;
      const label = button.querySelector(".btn-label");
      if (label) label.textContent = busy ? labelBusy : labelIdle;
    }

    async function toggleMonitor(start) {
      if (monitorBusy) return;
      monitorBusy = true;
      renderQuickActions();
      try {
        const audio = (state.settings && state.settings.audio) || {};
        const payload = { dir: audio.input_dir || undefined, process_existing: false };
        await (start ? endpoints.monitorStart(payload) : endpoints.monitorStop());
        toast.success(start ? t("monitor.startOk") : t("monitor.stopOk"));
        await loadMonitor({ silent: true });
      } catch (err) {
        toast.error(err);
      } finally {
        monitorBusy = false;
        renderQuickActions();
      }
    }

    async function clearFinished() {
      try {
        const result = await endpoints.clearJobs();
        toast.success(t("dashboard.cleared", { count: (result && result.removed) || 0 }));
        await loadJobs({ silent: true });
      } catch (err) {
        toast.error(err);
      }
    }

    async function chooseFile() {
      browseButton.disabled = true;
      try {
        const result = await endpoints.fileDialog("audio", t("dashboard.browseFile"));
        if (result && !result.canceled && result.path) await enqueuePath(result.path);
      } catch (err) {
        toast.show({ level: "error", message: t("config.browseFailed"), detail: errorFull(err) });
      } finally {
        browseButton.disabled = false;
      }
    }

    async function enqueuePath(path) {
      const value = String(path || "").trim();
      if (!value) {
        toast.warning(t("dashboard.pathRequired"));
        return;
      }
      enqueueButton.disabled = true;
      try {
        const job = await endpoints.enqueueJob({ input: value, source: "manual" });
        toast.success(t("dashboard.enqueued", { name: (job && (job.basename || basename(value))) || basename(value) }));
        filePathInput.value = "";
        await loadJobs({ silent: true });
      } catch (err) {
        toast.error(err);
      } finally {
        enqueueButton.disabled = false;
      }
    }

    function droppedPaths(dataTransfer) {
      const paths = [];
      if (!dataTransfer) return paths;
      const files = Array.from(dataTransfer.files || []);
      for (const file of files) {
        if (file.path) paths.push(file.path);
      }
      if (!paths.length && files.length) {
        let uriList = "";
        try {
          uriList = dataTransfer.getData("text/uri-list") || dataTransfer.getData("text/plain") || "";
        } catch (err) {
          uriList = "";
        }
        for (const line of uriList.split(/\r?\n/)) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("file:///")) continue;
          try {
            const url = new URL(trimmed);
            let path = decodeURIComponent(url.pathname);
            if (/^\/[A-Za-z]:/.test(path)) path = path.slice(1);
            paths.push(path.replace(/\//g, "\\"));
          } catch (err) {
            /* URI non valido */
          }
        }
      }
      return paths;
    }

    async function handleDrop(event) {
      event.preventDefault();
      dropZone.classList.remove("is-dragover");
      const paths = droppedPaths(event.dataTransfer);
      if (!paths.length) {
        toast.warning(t("dashboard.dropUnsupported"));
        return;
      }
      for (const path of paths) await enqueuePath(path);
    }

    async function refreshAll() {
      refreshButton.disabled = true;
      await Promise.allSettled([loadHealth(), loadEngineStatus(), loadJobs(), loadHardware(), loadMonitor({ silent: true })]);
      refreshButton.disabled = false;
    }

    /* ------------------------------------------------------------ events */
    dropZone.addEventListener("dragenter", (event) => {
      event.preventDefault();
      dropZone.classList.add("is-dragover");
    });
    dropZone.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      dropZone.classList.add("is-dragover");
    });
    dropZone.addEventListener("dragleave", (event) => {
      if (!dropZone.contains(event.relatedTarget)) dropZone.classList.remove("is-dragover");
    });
    dropZone.addEventListener("drop", handleDrop);
    browseButton.addEventListener("click", chooseFile);
    enqueueButton.addEventListener("click", () => enqueuePath(filePathInput.value));
    filePathInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        enqueuePath(filePathInput.value);
      }
    });
    refreshButton.addEventListener("click", refreshAll);
    clearButton.addEventListener("click", clearFinished);

    /* ------------------------------------------------------- store wiring */
    unsub = subscribe((reason) => {
      if (reason === "jobs") {
        board.setJobs(state.jobs);
        renderStats();
        renderRecent();
      } else if (reason === "job-log") {
        if (state.lastJobLog) board.appendJobLog(state.lastJobLog.job_id, state.lastJobLog.message);
      } else if (["engine", "health", "hardware", "settings", "health"].includes(reason)) {
        renderStatusCards();
      } else if (reason === "monitor") {
        renderQuickActions();
      }
    });

    /* --------------------------------------------------------- first load */
    board.setJobs(state.jobs);
    renderStats();
    renderRecent();
    renderQuickActions();
    renderStatusCards();
    await Promise.allSettled([loadJobs(), loadMonitor({ silent: true }), loadHealth()]);
    await Promise.allSettled([loadEngineStatus(), loadHardware()]);

    return () => {
      if (unsub) unsub();
      if (board) board.destroy();
    };
  },
};
