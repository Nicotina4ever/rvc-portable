/* RVC Portable — vista Addestramento: dataset -> prerequisiti -> training -> risultato. */
import { h, div, span, icon, clear, appendAll, formatDateTime } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { card, btn, badge, emptyState, kvRow, progressBar, setProgress } from "../components/ui.js";
import { textField, selectField, switchField, pathField } from "../components/fields.js";
import { toast } from "../components/toast.js";

const STAGE_LABELS = {
  queued: "training.stageQueued",
  dataset: "training.stageDataset",
  assets: "training.stageAssets",
  preprocess: "training.stagePreprocess",
  f0: "training.stageF0",
  hubert: "training.stageHubert",
  filelist: "training.stageFilelist",
  train: "training.stageTrain",
  index: "training.stageIndex",
  finalize: "training.stageFinalize",
  completed: "training.stageCompleted",
  failed: "training.statusFailed",
  canceled: "training.statusCanceled",
};

const STATUS_TONE = {
  queued: "info",
  running: "accent",
  completed: "ok",
  failed: "bad",
  canceled: "warn",
};

function stageLabel(stage) {
  const key = STAGE_LABELS[stage];
  return key ? t(key) : stage || "—";
}

function statusLabel(status) {
  const key = "training.status" + String(status || "").replace(/^./, (c) => c.toUpperCase());
  return t(key);
}

function statusBadge(status) {
  const tone = STATUS_TONE[status] || "neutral";
  return badge(statusLabel(status), tone);
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return t("training.durationMinutes", { minutes: minutes });
  const hours = Math.floor(minutes / 60);
  return t("training.durationHours", { hours: hours, minutes: minutes % 60 });
}

export const trainingView = {
  id: "training",
  titleKey: "nav.training",

  async mount(root, ctx) {
    let unsub = null;
    let capabilities = null;
    let jobs = [];
    let report = null;
    let selectedJobId = null;
    let selectedJob = null;
    let logTotal = 0;
    let logLines = [];
    let logFollow = true;
    let logLimit = 500;
    let pollTimer = null;
    let busy = false;

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("training.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("training.subtitle") });
    const refreshButton = btn(t("common.refresh"), { variant: "ghost", iconName: "refresh" });
    const startButton = btn(t("training.start"), { variant: "primary", iconName: "play", disabled: true });
    const header = div(
      "view-header",
      div("view-heading", title, subtitle),
      div("view-actions", refreshButton, startButton)
    );

    const capabilityCard = card({ title: t("training.capabilities"), className: "training-card" });
    const formCard = card({ title: t("training.dataset"), className: "training-card" });
    const reportHost = div("training-report");
    const settingsCard = card({ title: t("training.settings"), className: "training-card" });
    const progressCard = card({ title: t("training.progress"), className: "training-card" });
    const progressBody = div("training-progress");
    progressCard.body.appendChild(progressBody);
    progressCard.hidden = true;
    const jobsCard = card({ title: t("training.jobs"), className: "training-card" });
    const jobsHost = div("training-jobs");
    jobsCard.body.appendChild(jobsHost);

    const layout = div("training-layout", capabilityCard, formCard, reportHost, settingsCard, progressCard, jobsCard);
    root.append(header, layout);

    /* ------------------------------------------------------------- campi */
    const sourceField = textField({
      id: "train-source",
      label: t("training.sourceLabel"),
      mono: true,
      placeholder: t("training.sourcePlaceholder"),
      hint: t("training.sourceHint"),
    });
    const analyzeButton = btn(t("training.analyze"), { variant: "secondary", iconName: "search" });
    const folderButton = btn(t("training.browseFolder"), { variant: "ghost", iconName: "folder" });
    const zipButton = btn(t("training.browseZip"), { variant: "ghost", iconName: "file-audio" });
    const nameField = textField({
      id: "train-name",
      label: t("training.nameLabel"),
      placeholder: t("training.namePlaceholder"),
      hint: t("training.nameHint"),
    });
    formCard.body.append(
      sourceField.el,
      div("button-row button-row-wrap", folderButton, zipButton, analyzeButton),
      nameField.el
    );

    const presetSelect = selectField({
      id: "train-preset",
      label: t("training.preset"),
      value: "bilanciato",
      options: [
        { value: "veloce", label: t("training.presetFast") },
        { value: "bilanciato", label: t("training.presetBalanced") },
        { value: "qualita", label: t("training.presetQuality") },
      ],
    });
    const sampleRateSelect = selectField({
      id: "train-sr",
      label: t("training.sampleRate"),
      value: "48000",
      options: [
        { value: "48000", label: "48 kHz" },
        { value: "40000", label: "40 kHz" },
        { value: "32000", label: "32 kHz" },
      ],
    });
    const versionSelect = selectField({
      id: "train-version",
      label: t("training.version"),
      value: "v2",
      options: [
        { value: "v2", label: "v2" },
        { value: "v1", label: "v1" },
      ],
    });
    const f0Switch = switchField({
      id: "train-f0",
      label: t("training.f0"),
      checked: true,
      hint: t("training.f0Hint"),
    });
    const f0MethodSelect = selectField({
      id: "train-f0-method",
      label: t("training.f0Method"),
      value: "rmvpe",
      options: [
        { value: "rmvpe", label: "RMVPE" },
        { value: "pm", label: "Parselmouth (pm)" },
      ],
    });
    const epochsField = textField({ id: "train-epochs", label: t("training.epochs"), value: "250", type: "number" });
    const batchField = textField({ id: "train-batch", label: t("training.batch"), value: "6", type: "number" });
    const saveEveryField = textField({ id: "train-save", label: t("training.saveEvery"), value: "20", type: "number" });
    const testSampleField = pathField({
      id: "train-test-sample",
      kind: "audio",
      label: t("training.testSample"),
      hint: t("training.testSampleHint"),
    });
    const evaluateSwitch = switchField({
      id: "train-evaluate",
      label: t("training.evaluate"),
      checked: true,
      hint: t("training.evaluateHint"),
    });
    const finetuneField = pathField({
      id: "train-finetune",
      kind: "model",
      label: t("training.finetune"),
      hint: t("training.finetuneHint"),
    });

    const advanced = h(
      "details",
      { class: "training-advanced" },
      h("summary", { text: t("training.advanced") }),
      div("field-grid", epochsField.el, batchField.el, saveEveryField.el),
      finetuneField.el,
      testSampleField.el,
      evaluateSwitch.el
    );
    settingsCard.body.append(
      presetSelect.el,
      div("field-grid", sampleRateSelect.el, versionSelect.el),
      f0Switch.el,
      f0MethodSelect.el,
      advanced
    );

    /* ------------------------------------------------------------ helpers */
    function setBusy(next) {
      busy = Boolean(next);
      renderActions();
    }

    function currentPreset() {
      return (capabilities && capabilities.presets || []).find((item) => item.id === presetSelect.getValue()) || null;
    }

    function applyPreset() {
      const preset = currentPreset();
      if (!preset) return;
      epochsField.setValue(preset.epochs);
      batchField.setValue(preset.batch_size);
      saveEveryField.setValue(preset.save_every);
    }

    function assetsReady() {
      return Boolean(capabilities && capabilities.assets && capabilities.assets.ready);
    }

    function hasActiveJob() {
      return Boolean(
        capabilities &&
          ((capabilities.active && capabilities.active !== "") || Number(capabilities.pending || 0) > 0)
      );
    }

    function canStart() {
      return Boolean(report && report.ready && assetsReady() && !busy && !hasActiveJob());
    }

    function renderActions() {
      startButton.disabled = !canStart();
      analyzeButton.disabled = busy;
      folderButton.disabled = busy;
      zipButton.disabled = busy;
    }

    /* -------------------------------------------------------- capabilities */
    function renderCapabilities() {
      clear(capabilityCard.body);
      if (!capabilities) {
        capabilityCard.body.appendChild(emptyState({ iconName: "alert", title: t("training.unavailable"), text: "" }));
        return;
      }
      const cuda = capabilities.cuda || {};
      const assets = capabilities.assets || {};
      const items = [
        div(
          "status-row",
          span("status-dot dot-" + (cuda.available ? "ok" : "neutral")),
          span("status-value", cuda.available ? t("training.gpuReady") : t("training.gpuMissing")),
          cuda.vram_gb ? badge(cuda.vram_gb + " GB", "accent") : null
        ),
        cuda.name ? h("p", { class: "status-message", text: cuda.name }) : null,
        div(
          "status-stats",
          div("status-stat", span("stat-value", (capabilities.disk_free_gb || 0) + " GB"), span("stat-label", t("training.diskFree"))),
          div("status-stat", span("stat-value", (assets.issues || []).length), span("stat-label", t("training.assetIssues")))
        )
      ];
      appendAll(capabilityCard.body, items);
      if (assets.issues && assets.issues.length) {
        capabilityCard.body.appendChild(
          div(
            "inline-alert",
            h("p", { text: t("training.assetsMissing") }),
            h("ul", {}, ...assets.issues.map((issue) => h("li", { text: issue })))
          )
        );
      }
      if (!cuda.available) {
        capabilityCard.body.appendChild(
          h("p", { class: "field-hint", text: t("training.gpuHint") })
        );
      }
    }

    /* -------------------------------------------------------------- report */
    function renderReport() {
      clear(reportHost);
      if (!report) return;
      const wrapper = card({ title: t("training.report"), className: "training-card" });
      const ready = Boolean(report.ready);
      appendAll(
        wrapper.body,
        div(
          "status-row",
          span("status-dot dot-" + (ready ? "ok" : "bad")),
          span("status-value", ready ? t("training.reportReady") : t("training.reportNotReady"))
        ),
        kvRow(t("training.files"), String(report.files || 0)),
        kvRow(t("training.totalDuration"), formatDuration(report.total_s)),
        kvRow(t("training.sampleRates"), (report.sample_rates || []).join(", ") || "—"),
        kvRow(t("training.channels"), (report.channels || []).join(", ") || "—")
      );
      if (report.warnings && report.warnings.length) {
        wrapper.body.appendChild(
          div("inline-alert", h("ul", {}, ...report.warnings.map((item) => h("li", { text: item }))))
        );
      }
      if (report.errors && report.errors.length) {
        wrapper.body.appendChild(
          div("inline-alert", h("ul", {}, ...report.errors.map((item) => h("li", { text: item }))))
        );
      }
      reportHost.appendChild(wrapper);
      renderActions();
    }

    /* --------------------------------------------------------------- jobs */
    function renderJobs() {
      clear(jobsHost);
      if (!jobs.length) {
        jobsHost.appendChild(h("p", { class: "field-hint", text: t("training.noJobs") }));
        return;
      }
      const list = h("ul", { class: "training-job-list" });
      jobs.forEach((job) => {
        const row = h(
          "li",
          { class: "training-job" + (job.id === selectedJobId ? " is-selected" : "") },
          div(
            "training-job-main",
            h("span", { class: "training-job-name", text: job.name || job.id }),
            statusBadge(job.status),
            h("span", { class: "training-job-meta", text: formatDateTime(job.created_at) })
          ),
          div(
            "training-job-actions",
            btn(t("training.open"), {
              variant: "ghost",
              onClick: () => {
                selectJob(job.id);
              },
            })
          )
        );
        list.appendChild(row);
      });
      jobsHost.appendChild(list);
    }

    /* ----------------------------------------------------------- progress */
    function renderProgress() {
      clear(progressBody);
      progressCard.hidden = !selectedJob;
      if (!selectedJob) return;
      const job = selectedJob;
      const active = job.status === "running" || job.status === "queued";
      const bar = progressBar(Number(job.progress || 0), t("training.progressLabel"));
      appendAll(
        progressBody,
        div(
          "status-row",
          span("status-dot dot-" + (job.status === "completed" ? "ok" : active ? "accent" : "neutral")),
          h("span", { class: "status-value", text: job.name || job.id }),
          statusBadge(job.status)
        ),
        bar,
        kvRow(t("training.stage"), stageLabel(job.stage)),
        kvRow(t("training.progressLabel"), Math.round(Number(job.progress || 0)) + "%"),
        job.total_epochs
          ? kvRow(t("training.epoch"), String(job.epoch || 0) + " / " + String(job.total_epochs))
          : null,
        job.loss !== null && job.loss !== undefined ? kvRow(t("training.loss"), String(job.loss)) : null,
        job.message ? kvRow(t("training.message"), job.message) : null,
        job.error ? div("inline-alert", h("p", { text: job.error })) : null,
        job.output && job.output.model
          ? kvRow(t("training.outputModel"), job.output.model)
          : null,
        job.output && job.output.index
          ? kvRow(t("training.outputIndex"), job.output.index)
          : null,
        job.output && job.output.best_checkpoint
          ? kvRow(t("training.bestCheckpoint"), basename(job.output.best_checkpoint))
          : null
      );

      const actions = div("button-row button-row-wrap");
      if (active) {
        actions.appendChild(
          btn(t("training.cancel"), { variant: "danger", iconName: "stop", onClick: () => cancelJob(job.id) })
        );
      }
      if (job.status === "failed" || job.status === "canceled") {
        actions.appendChild(
          btn(t("training.resume"), { variant: "secondary", iconName: "refresh", onClick: () => resumeJob(job.id) })
        );
      }
      if (job.status === "completed") {
        actions.appendChild(
          btn(t("training.test"), { variant: "primary", iconName: "play", onClick: () => testJob(job.id) })
        );
      }
      if (!active) {
        actions.appendChild(
          btn(t("training.delete"), { variant: "ghost", iconName: "trash", onClick: () => deleteJob(job.id) })
        );
      }
      progressBody.appendChild(actions);

      if (job.output && Array.isArray(job.output.evaluations) && job.output.evaluations.length) {
        const evalList = h("ol", { class: "training-evals" });
        job.output.evaluations.forEach((entry) => {
          const score = Number.isFinite(Number(entry.score)) ? Number(entry.score).toFixed(1) : "—";
          const cents = Number.isFinite(Number(entry.f0_rmse_cents)) ? Number(entry.f0_rmse_cents).toFixed(0) : "—";
          evalList.appendChild(
            h("li", { text: `${entry.checkpoint}: ${score}/100 · F0 ${cents} cents` })
          );
        });
        progressBody.appendChild(
          div(
            "training-evals-box",
            h("p", { class: "training-evals-title", text: t("training.evaluations") }),
            evalList
          )
        );
      }
      const logMeta = t("training.logMeta", { shown: logLines.length, total: logTotal });
      const followButton = btn(logFollow ? t("training.logFollowOn") : t("training.logFollow"), {
        variant: logFollow ? "primary" : "ghost",
        onClick: () => {
          logFollow = !logFollow;
          renderProgress();
        },
      });
      const copyButton = btn(t("training.logCopy"), {
        variant: "ghost",
        onClick: async () => {
          try {
            await navigator.clipboard.writeText(logLines.join("\n"));
            toast.success(t("training.logCopied"));
          } catch (err) {
            toast.error(err);
          }
        },
      });
      const limitSelect = h("select", { class: "input training-log-select", "aria-label": t("training.logLines") });
      [200, 500, 1000, 2000].forEach((value) => {
        const option = h("option", { value: String(value), text: String(value) });
        if (value === logLimit) option.selected = true;
        limitSelect.appendChild(option);
      });
      limitSelect.addEventListener("change", async () => {
        logLimit = Number(limitSelect.value) || 500;
        await refreshLog();
        renderProgress();
      });
      progressBody.appendChild(
        div(
          "training-log-head",
          div("training-log-titles", span("training-log-title", t("training.log")), span("training-log-meta", logMeta)),
          div("training-log-toolbar", followButton, copyButton, limitSelect)
        )
      );
      const logBox = h("pre", { class: "training-log", "aria-label": t("training.log") });
      logBox.textContent = logLines.join("\n");
      logBox.addEventListener("scroll", () => {
        const nearBottom = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 24;
        if (!nearBottom && logFollow) {
          logFollow = false;
          followButton.textContent = t("training.logFollow");
          followButton.classList.remove("btn-primary");
          followButton.classList.add("btn-ghost");
        }
      });
      progressBody.appendChild(logBox);
      if (logFollow) {
        requestAnimationFrame(() => {
          logBox.scrollTop = logBox.scrollHeight;
        });
      }
    }

    /* ------------------------------------------------------------- actions */
    async function loadCapabilities() {
      try {
        const data = await endpoints.trainingStatus();
        capabilities = data.capabilities || null;
        jobs = data.jobs || [];
        if (capabilities && capabilities.defaults) {
          sampleRateSelect.setValue(String(capabilities.defaults.sample_rate || 48000));
          versionSelect.setValue(String(capabilities.defaults.version || "v2"));
          f0Switch.setValue(Boolean(capabilities.defaults.f0));
          f0MethodSelect.setValue(String(capabilities.defaults.f0_method || "rmvpe"));
        }
        if (capabilities && capabilities.active) {
          selectedJobId = capabilities.active;
        }
        renderCapabilities();
        renderJobs();
        renderActions();
        if (selectedJobId) await refreshJob();
        ensurePolling();
      } catch (err) {
        clear(capabilityCard.body);
        capabilityCard.body.appendChild(
          emptyState({
            iconName: "alert",
            title: t("training.unavailable"),
            text: errorFull(err),
          })
        );
      }
    }

    async function analyze() {
      const source = sourceField.getValue().trim();
      if (!source) {
        toast.warning(t("training.sourceRequired"));
        return;
      }
      setBusy(true);
      try {
        const data = await endpoints.trainingAnalyze(source);
        report = data.report || null;
        renderReport();
        toast.success(t("training.analyzeDone"));
      } catch (err) {
        report = null;
        renderReport();
        toast.error(err);
      } finally {
        setBusy(false);
        renderActions();
      }
    }

    function payload() {
      return {
        source: sourceField.getValue().trim(),
        name: nameField.getValue().trim() || t("training.defaultName"),
        preset: presetSelect.getValue(),
        overrides: {
          sample_rate: Number(sampleRateSelect.getValue()),
          version: versionSelect.getValue(),
          f0: f0Switch.getValue(),
          f0_method: f0MethodSelect.getValue(),
          epochs: Number(epochsField.getValue() || 250),
          batch_size: Number(batchField.getValue() || 6),
          save_every: Number(saveEveryField.getValue() || 20),
        },
        finetune_model: finetuneField.getValue().trim(),
        test_sample: testSampleField.getValue().trim(),
        evaluate_checkpoints: evaluateSwitch.getValue(),
      };
    }

    async function startTraining() {
      if (!canStart()) return;
      setBusy(true);
      try {
        const data = await endpoints.trainingStart(payload());
        selectedJobId = data.job && data.job.id;
        jobs = data.jobs || jobs;
        renderJobs();
        await refreshJob();
        ensurePolling();
        toast.success(t("training.started"));
      } catch (err) {
        toast.error(err);
      } finally {
        setBusy(false);
        renderActions();
      }
    }

    async function refreshLog() {
      if (!selectedJobId) return;
      try {
        const offset = Math.max(0, (logTotal || 0) - logLimit);
        const data = await endpoints.trainingLog(selectedJobId, offset, logLimit);
        logLines = Array.isArray(data.lines) ? data.lines : [];
        logTotal = Number.isFinite(Number(data.total)) ? Number(data.total) : logLines.length;
      } catch (err) {
        logLines = [];
        logTotal = 0;
      }
    }

    async function refreshJob() {
      if (!selectedJobId) return;
      try {
        const data = await endpoints.trainingGet(selectedJobId);
        selectedJob = data.job || null;
        if (selectedJob) {
          await refreshLog();
        }
      } catch (err) {
        selectedJob = null;
      }
      renderProgress();
    }

    function selectJob(jobId) {
      selectedJobId = jobId;
      logTotal = 0;
      logLines = [];
      logFollow = true;
      renderJobs();
      refreshJob();
      ensurePolling();
    }

    async function cancelJob(jobId) {
      try {
        const data = await endpoints.trainingCancel(jobId);
        selectedJob = data.job || selectedJob;
        renderProgress();
        toast.info(t("training.cancelRequested"));
      } catch (err) {
        toast.error(err);
      }
    }

    async function resumeJob(jobId) {
      try {
        await endpoints.trainingResume(jobId);
        toast.success(t("training.resumed"));
        await loadCapabilities();
      } catch (err) {
        toast.error(err);
      }
    }

    async function testJob(jobId) {
      try {
        await endpoints.trainingTest(jobId, "");
        toast.success(t("training.testQueued"));
      } catch (err) {
        toast.error(err);
      }
    }

    async function deleteJob(jobId) {
      try {
        await endpoints.trainingDelete(jobId);
        if (selectedJobId === jobId) {
          selectedJobId = null;
          selectedJob = null;
          renderProgress();
        }
        toast.success(t("training.deleted"));
        await loadCapabilities();
      } catch (err) {
        toast.error(err);
      }
    }

    function ensurePolling() {
      const active = Boolean(
        selectedJob && (selectedJob.status === "running" || selectedJob.status === "queued")
      );
      if (active && !pollTimer) {
        pollTimer = setInterval(() => {
          refreshJob();
        }, 1500);
      } else if (!active && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    async function browse(kind) {
      try {
        const result = await endpoints.fileDialog(kind, t("training.sourceLabel"), sourceField.getValue());
        if (result && result.path) sourceField.setValue(result.path);
      } catch (err) {
        toast.error(err);
      }
    }

    /* -------------------------------------------------------------- events */
    presetSelect.select.addEventListener("change", applyPreset);
    sourceField.input.addEventListener("change", () => {
      report = null;
      renderReport();
    });
    folderButton.addEventListener("click", () => browse("directory"));
    zipButton.addEventListener("click", () => browse("file"));
    analyzeButton.addEventListener("click", analyze);
    startButton.addEventListener("click", startTraining);
    refreshButton.addEventListener("click", () => {
      loadCapabilities();
    });

    if (ctx && typeof ctx.onCleanup === "function") {
      // il router usa il valore di ritorno; nessuna registrazione extra
    }

    await loadCapabilities();
    applyPreset();

    return () => {
      if (pollTimer) clearInterval(pollTimer);
      if (unsub) unsub();
    };
  },
};
