/* RVC Portable — coda job: card con progress, annullamento, player e log. */
import { h, div, span, icon, clear, basename, formatDuration, formatClock, timeAgo } from "../core/dom.js";
import { t, hasKey } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { state, removeJobFromState, setState } from "../core/store.js";
import { applyJob } from "../core/data.js";
import { btn, badge, progressBar, setProgress, emptyState } from "./ui.js";
import { confirmModal } from "./modal.js";
import { toast } from "./toast.js";
import { createPlayer } from "./player.js";

const STATE_VARIANTS = {
  queued: "info",
  running: "accent",
  done: "ok",
  failed: "bad",
  canceled: "neutral",
};

const STATE_LABELS = {
  queued: "job.stateQueued",
  running: "job.stateRunning",
  done: "job.stateDone",
  failed: "job.stateFailed",
  canceled: "job.stateCanceled",
};

const STAGE_LABELS = {
  loading: "job.stageLoading",
  extract: "job.stageExtract",
  f0: "job.stageF0",
  features: "job.stageFeatures",
  synthesize: "job.stageSynthesize",
  write: "job.stageWrite",
  done: "job.stageDone",
  retry: "job.stageRetry",
};

function rank(job) {
  if (job.state === "running") return 0;
  if (job.state === "queued") return 1;
  return 2;
}

function sortJobs(jobs) {
  return jobs.slice().sort((left, right) => {
    const diff = rank(left) - rank(right);
    if (diff !== 0) return diff;
    if (rank(left) < 2) return (left.created_at || 0) - (right.created_at || 0);
    return (right.finished_at || right.created_at || 0) - (left.finished_at || left.created_at || 0);
  });
}

function jobErrorText(job) {
  const code = job.error_code || "";
  if (code && hasKey("errors." + code)) {
    const translated = t("errors." + code);
    const raw = job.error_message || "";
    return raw && raw !== translated ? translated + " — " + raw : translated;
  }
  return job.error_message || job.detail || t("errors.generic");
}

export function createJobBoard(options = {}) {
  const el = div("job-board");
  const empty = emptyState({
    iconName: "inbox",
    title: options.emptyTitle || t("dashboard.queueEmpty"),
    text: options.emptyText || t("dashboard.queueEmptyHint"),
  });
  el.appendChild(empty);
  const cards = new Map();

  function renderLogs(entry) {
    const logs = state.jobLogs[entry.job.id] || [];
    clear(entry.refs.logHost);
    entry.refs.logHost.appendChild(h("h4", { class: "job-log-title", text: t("dashboard.jobLog") }));
    if (!logs.length) {
      entry.refs.logHost.appendChild(h("p", { class: "job-log-empty", text: t("dashboard.jobLogEmpty") }));
      return;
    }
    const list = h("ul", { class: "job-log" });
    for (const item of logs.slice(-80)) {
      list.appendChild(
        h(
          "li",
          { class: "job-log-line" },
          h("span", { class: "job-log-time", text: formatClock(item.ts) }),
          h("span", { class: "job-log-message", text: item.message })
        )
      );
    }
    entry.refs.logHost.appendChild(list);
    list.scrollTop = list.scrollHeight;
  }

  function ensurePlayer(entry) {
    if (entry.player) {
      entry.player.setJob(entry.job);
      return;
    }
    entry.player = createPlayer({ job: entry.job, initialSide: entry.job.state === "done" ? "output" : "input" });
    clear(entry.refs.playerHost);
    entry.refs.playerHost.appendChild(entry.player.el);
  }

  function toggleDetails(entry) {
    entry.expanded = !entry.expanded;
    entry.refs.detail.hidden = !entry.expanded;
    entry.refs.detailsBtn.setAttribute("aria-expanded", String(entry.expanded));
    entry.refs.detailsBtn.classList.toggle("is-open", entry.expanded);
    if (entry.expanded) {
      ensurePlayer(entry);
      renderLogs(entry);
      entry.refs.detail.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  async function requestCancel(entry) {
    const confirmed = await confirmModal({
      title: t("job.cancelTitle"),
      message: t("job.cancelText"),
      confirmLabel: t("job.cancelConfirm"),
      danger: true,
    });
    if (!confirmed) return;
    try {
      const updated = await endpoints.cancelJob(entry.job.id);
      applyJob(updated);
      toast.success(t("job.canceled"));
    } catch (err) {
      toast.error(err);
    }
  }

  async function requestRemove(entry) {
    const confirmed = await confirmModal({
      title: t("job.removeTitle"),
      message: t("job.removeText"),
      confirmLabel: t("job.removeConfirm"),
      danger: false,
    });
    if (!confirmed) return;
    try {
      await endpoints.deleteJob(entry.job.id);
      removeJobFromState(entry.job.id);
      setState("jobs");
    } catch (err) {
      toast.error(err);
    }
  }

  function buildCard(job) {
    const stateBadge = badge("", "neutral");
    const name = h("h3", { class: "job-name" });
    const sourceBadge = badge("", "neutral");
    const stageLabel = span("job-meta-item job-stage");
    const createdLabel = span("job-meta-item job-created");
    const elapsedLabel = span("job-meta-item job-elapsed");
    const retriesLabel = span("job-meta-item job-retries");
    const progress = progressBar(0, t("dashboard.queue"));
    const errorBox = h("p", { class: "job-error", hidden: true });
    const cancelButton = btn("", {
      variant: "ghost",
      iconName: "stop",
      ariaLabel: t("dashboard.cancel"),
      title: t("dashboard.cancel"),
      className: "job-action-cancel",
    });
    const removeButton = btn("", {
      variant: "ghost",
      iconName: "trash",
      ariaLabel: t("dashboard.remove"),
      title: t("dashboard.remove"),
      className: "job-action-remove",
    });
    const downloadLink = h(
      "a",
      { class: "btn btn-ghost btn-icon job-action-download", title: t("dashboard.download"), "aria-label": t("dashboard.download") },
      icon("download")
    );
    const detailsButton = btn(t("common.details"), {
      variant: "ghost",
      iconName: "chevron-down",
      className: "job-details-toggle",
    });
    detailsButton.setAttribute("aria-expanded", "false");

    const detail = div("job-detail", { hidden: true });
    const playerHost = div("job-player");
    const logHost = div("job-log-host");
    detail.append(playerHost, logHost);

    const head = div(
      "job-head",
      div(
        "job-main",
        div("job-title-row", stateBadge, name, sourceBadge),
        div("job-meta", stageLabel, createdLabel, elapsedLabel, retriesLabel)
      ),
      div("job-actions", cancelButton, removeButton, downloadLink, detailsButton)
    );

    const node = h("article", { class: "job-card", dataset: { state: job.state } }, head, progress, errorBox, detail);
    const entry = {
      node,
      job,
      expanded: false,
      player: null,
      refs: {
        stateBadge,
        name,
        sourceBadge,
        stageLabel,
        createdLabel,
        elapsedLabel,
        retriesLabel,
        progress,
        errorBox,
        cancelButton,
        removeButton,
        downloadLink,
        detailsButton,
        detail,
        playerHost,
        logHost,
      },
    };

    cancelButton.addEventListener("click", () => requestCancel(entry));
    removeButton.addEventListener("click", () => requestRemove(entry));
    detailsButton.addEventListener("click", () => toggleDetails(entry));
    return entry;
  }

  function updateCard(entry, job) {
    entry.job = job;
    const refs = entry.refs;
    const variant = STATE_VARIANTS[job.state] || "neutral";
    refs.stateBadge.className = "badge badge-" + variant;
    refs.stateBadge.textContent = t(STATE_LABELS[job.state] || "common.unknown");
    refs.name.textContent = job.basename || basename(job.input_path) || "—";
    refs.name.title = job.input_path || "";
    refs.sourceBadge.textContent = job.source === "monitor" ? t("job.sourceMonitor") : t("job.sourceManual");
    refs.sourceBadge.className = "badge badge-" + (job.source === "monitor" ? "accent" : "neutral");
    refs.stageLabel.textContent = job.stage ? t(STAGE_LABELS[job.stage] || "job.stageUnknown") : "";
    refs.createdLabel.textContent = job.created_at ? t("dashboard.created", { time: timeAgo(job.created_at) }) : "";
    const now = Date.now() / 1000;
    const elapsed = job.elapsed_s || (job.started_at ? Math.max(0, (job.finished_at || now) - job.started_at) : 0);
    refs.elapsedLabel.textContent = elapsed > 0 ? t("dashboard.elapsed", { time: formatDuration(elapsed) }) : "";
    refs.retriesLabel.textContent = job.retries ? t("dashboard.retries", { count: job.retries }) : "";

    const active = job.state === "queued" || job.state === "running";
    refs.cancelButton.hidden = !active;
    refs.removeButton.hidden = active;
    setProgress(refs.progress, job.state === "done" ? 100 : Number(job.progress) || 0);
    refs.progress.hidden = job.state === "canceled" && !job.progress;

    if (job.error_message) {
      refs.errorBox.hidden = false;
      refs.errorBox.textContent = t("dashboard.errorLabel") + ": " + jobErrorText(job);
      if (job.detail) refs.errorBox.title = job.detail;
    } else {
      refs.errorBox.hidden = true;
      refs.errorBox.removeAttribute("title");
    }

    const canDownload = job.state === "done" && job.output_path;
    refs.downloadLink.hidden = !canDownload;
    if (canDownload) {
      refs.downloadLink.setAttribute("href", endpoints.audioUrl(job.id, "output"));
      refs.downloadLink.setAttribute("download", basename(job.output_path));
    } else {
      refs.downloadLink.removeAttribute("href");
      refs.downloadLink.removeAttribute("download");
    }

    entry.node.dataset.state = job.state;
    entry.node.setAttribute("aria-busy", job.state === "running" ? "true" : "false");
    if (entry.player) entry.player.setJob(job);
    if (entry.expanded) renderLogs(entry);
  }

  function destroyEntry(entry) {
    if (entry.player) {
      entry.player.destroy();
      entry.player = null;
    }
    entry.node.remove();
  }

  function setJobs(nextJobs) {
    const ordered = sortJobs(Array.isArray(nextJobs) ? nextJobs : []);
    const known = new Set(ordered.map((job) => job.id));
    for (const [id, entry] of Array.from(cards.entries())) {
      if (!known.has(id)) {
        destroyEntry(entry);
        cards.delete(id);
      }
    }
    for (const job of ordered) {
      let entry = cards.get(job.id);
      if (!entry) {
        entry = buildCard(job);
        cards.set(job.id, entry);
        el.appendChild(entry.node);
      }
      updateCard(entry, job);
      el.appendChild(entry.node);
    }
    empty.hidden = ordered.length > 0;
  }

  function appendJobLog(jobId, message) {
    const entry = cards.get(jobId);
    if (!entry || !entry.expanded) return;
    renderLogs(entry);
  }

  function destroy() {
    for (const entry of cards.values()) destroyEntry(entry);
    cards.clear();
  }

  return { el, setJobs, appendJobLog, destroy };
}
