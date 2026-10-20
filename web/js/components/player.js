/* RVC Portable — player audio con forma d'onda e seek (Range dal backend). */
import { h, div, span, icon, clear, formatDuration, clamp, basename } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { subscribe } from "../core/store.js";
import { btn } from "./ui.js";
import { toast } from "./toast.js";

const WAVE_HEIGHT = 64;

function normalizePeaks(raw) {
  if (!Array.isArray(raw)) return null;
  return raw.map((item) => {
    if (typeof item === "number") return clamp(Math.abs(item), 0, 1);
    if (item && typeof item === "object") {
      const max = Number(item.max ?? item.peak ?? 0);
      const min = Number(item.min ?? 0);
      return clamp(Math.max(Math.abs(max), Math.abs(min)), 0, 1);
    }
    return 0;
  });
}

export function createPlayer(options = {}) {
  const initialSide = options.initialSide === "input" ? "input" : "output";
  let job = options.job || {};
  let side = initialSide;
  let peaks = null;
  let duration = 0;
  let currentTime = 0;
  let loadToken = 0;
  let destroyed = false;
  let observer = null;
  let unsubscribe = null;
  let audioAvailable = true;

  const audio = h("audio", { preload: "metadata", class: "player-audio" });
  const canvas = h("canvas", { class: "waveform", "aria-hidden": "true" });
  const unavailable = div("player-empty", h("p", { class: "player-empty-text", text: t("dashboard.playerUnavailable") }));
  unavailable.hidden = true;
  const note = h("p", { class: "player-note", hidden: true });
  const playButton = btn("", { variant: "primary", iconName: "play", ariaLabel: t("common.play"), className: "player-play" });
  const seek = h("input", {
    type: "range",
    class: "seek",
    min: "0",
    max: "100",
    step: "0.1",
    value: "0",
    "aria-label": t("common.seek"),
  });
  const currentLabel = span("player-time player-time-current", "0:00");
  const totalLabel = span("player-time player-time-total", "0:00");
  const downloadLink = h(
    "a",
    { class: "btn btn-ghost btn-icon player-download", title: t("dashboard.download"), "aria-label": t("dashboard.download") },
    icon("download")
  );

  const tabInput = btn(t("dashboard.playerInput"), { variant: "ghost", className: "player-tab" });
  const tabOutput = btn(t("dashboard.playerOutput"), { variant: "ghost", className: "player-tab" });
  tabInput.setAttribute("role", "tab");
  tabOutput.setAttribute("role", "tab");
  const tabs = div("player-tabs", { role: "tablist", "aria-label": t("dashboard.player") }, tabInput, tabOutput);

  const stage = div("player-stage", canvas, unavailable);
  const controls = div("player-controls", playButton, currentLabel, seek, totalLabel, downloadLink);
  const el = div("player", tabs, stage, controls, note, audio);

  function currentPath() {
    return side === "output" ? job.output_path : job.input_path;
  }

  function setPlayIcon(playing) {
    clear(playButton);
    playButton.appendChild(icon(playing ? "pause" : "play"));
    playButton.setAttribute("aria-label", playing ? t("common.pause") : t("common.play"));
    playButton.classList.toggle("is-playing", playing);
  }

  function updateDownload() {
    const path = currentPath();
    if (path) {
      downloadLink.hidden = false;
      downloadLink.setAttribute("href", endpoints.audioUrl(job.id, side));
      downloadLink.setAttribute("download", basename(path));
    } else {
      downloadLink.hidden = true;
      downloadLink.removeAttribute("href");
      downloadLink.removeAttribute("download");
    }
  }

  function updateTimes() {
    currentLabel.textContent = formatDuration(currentTime);
    totalLabel.textContent = formatDuration(duration);
    seek.value = duration > 0 ? String((currentTime / duration) * 100) : "0";
  }

  function showUnavailable() {
    audioAvailable = false;
    unavailable.hidden = false;
    playButton.disabled = true;
    seek.disabled = true;
    draw();
  }

  function draw() {
    const ctx = canvas.getContext ? canvas.getContext("2d") : null;
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const cssWidth = canvas.clientWidth || el.clientWidth || 320;
    canvas.width = Math.max(1, Math.round(cssWidth * dpr));
    canvas.height = Math.round(WAVE_HEIGHT * dpr);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const styles = getComputedStyle(canvas);
    const playedColor = (styles.getPropertyValue("--wave-played") || "").trim() || "#8aa2ff";
    const restColor = (styles.getPropertyValue("--wave-rest") || "").trim() || "#33406a";
    const middle = canvas.height / 2;
    const progress = duration > 0 ? clamp(currentTime / duration, 0, 1) : 0;

    if (peaks && peaks.length) {
      const gap = Math.max(1, Math.round(dpr));
      const barWidth = Math.max(1, (canvas.width - gap * (peaks.length - 1)) / peaks.length);
      const maxBar = canvas.height - Math.round(8 * dpr);
      for (let index = 0; index < peaks.length; index += 1) {
        const x = index * (barWidth + gap);
        const barHeight = Math.max(Math.round(dpr), peaks[index] * maxBar);
        ctx.fillStyle = x / canvas.width <= progress ? playedColor : restColor;
        ctx.fillRect(x, middle - barHeight / 2, barWidth, barHeight);
      }
    } else {
      ctx.strokeStyle = restColor;
      ctx.lineWidth = Math.max(1, dpr);
      ctx.beginPath();
      ctx.moveTo(0, middle);
      ctx.lineTo(canvas.width, middle);
      ctx.stroke();
    }

    if (progress > 0) {
      ctx.fillStyle = playedColor;
      const x = Math.round(canvas.width * progress);
      ctx.fillRect(x, 0, Math.max(1, Math.round(dpr)), canvas.height);
    }
  }

  async function load() {
    loadToken += 1;
    const tokenId = loadToken;
    peaks = null;
    duration = 0;
    currentTime = 0;
    audioAvailable = true;
    note.hidden = true;
    unavailable.hidden = true;
    playButton.disabled = false;
    seek.disabled = false;
    setPlayIcon(false);
    audio.pause();
    updateTimes();
    updateDownload();
    const path = currentPath();
    if (!path) {
      showUnavailable();
      updateTimes();
      return;
    }
    audio.src = endpoints.audioUrl(job.id, side);
    try {
      audio.load();
    } catch (err) {
      /* alcuni browser lanciano se src non è valido */
    }
    draw();
    try {
      const data = await endpoints.waveform(job.id, side, 600);
      if (destroyed || tokenId !== loadToken) return;
      peaks = normalizePeaks(data && data.peaks);
      if (data && Number(data.duration_s) > 0 && !Number.isFinite(audio.duration)) duration = Number(data.duration_s);
      draw();
      if (!peaks || !peaks.length) {
        note.textContent = t("dashboard.waveformUnavailable");
        note.hidden = false;
      }
    } catch (err) {
      if (destroyed || tokenId !== loadToken) return;
      note.textContent = t("dashboard.waveformUnavailable");
      note.hidden = false;
      draw();
    }
  }

  function setSide(next) {
    const target = next === "input" ? "input" : "output";
    if (target === side && audio.src) return;
    side = target;
    tabInput.classList.toggle("is-active", side === "input");
    tabOutput.classList.toggle("is-active", side === "output");
    tabInput.setAttribute("aria-selected", String(side === "input"));
    tabOutput.setAttribute("aria-selected", String(side === "output"));
    load();
  }

  tabInput.addEventListener("click", () => setSide("input"));
  tabOutput.addEventListener("click", () => setSide("output"));
  tabInput.setAttribute("aria-selected", String(side === "input"));
  tabOutput.setAttribute("aria-selected", String(side === "output"));
  tabInput.classList.toggle("is-active", side === "input");
  tabOutput.classList.toggle("is-active", side === "output");

  playButton.addEventListener("click", async () => {
    if (!audioAvailable || !audio.src) return;
    if (audio.paused) {
      try {
        await audio.play();
      } catch (err) {
        toast.error(t("dashboard.playerUnavailable"));
      }
    } else {
      audio.pause();
    }
  });

  seek.addEventListener("input", () => {
    if (!Number.isFinite(duration) || duration <= 0) return;
    currentTime = (Number(seek.value) / 100) * duration;
    currentLabel.textContent = formatDuration(currentTime);
    draw();
  });
  seek.addEventListener("change", () => {
    if (!Number.isFinite(duration) || duration <= 0) return;
    try {
      audio.currentTime = (Number(seek.value) / 100) * duration;
    } catch (err) {
      /* seek non disponibile */
    }
  });

  canvas.addEventListener("click", (event) => {
    if (!audioAvailable || !Number.isFinite(duration) || duration <= 0) return;
    const rect = canvas.getBoundingClientRect();
    const fraction = clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
    currentTime = fraction * duration;
    try {
      audio.currentTime = currentTime;
    } catch (err) {
      /* seek non disponibile */
    }
    updateTimes();
    draw();
  });

  audio.addEventListener("loadedmetadata", () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) duration = audio.duration;
    updateTimes();
    draw();
  });
  audio.addEventListener("durationchange", () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) duration = audio.duration;
    updateTimes();
  });
  audio.addEventListener("timeupdate", () => {
    currentTime = Number(audio.currentTime) || 0;
    updateTimes();
    draw();
  });
  audio.addEventListener("play", () => setPlayIcon(true));
  audio.addEventListener("pause", () => setPlayIcon(false));
  audio.addEventListener("ended", () => setPlayIcon(false));
  audio.addEventListener("error", () => {
    if (destroyed) return;
    showUnavailable();
    updateTimes();
  });

  if (typeof ResizeObserver !== "undefined") {
    observer = new ResizeObserver(() => draw());
    observer.observe(canvas);
  }
  unsubscribe = subscribe((reason) => {
    if (reason === "theme") draw();
  });

  load();

  return {
    el,
    setJob(nextJob) {
      if (!nextJob) return;
      job = nextJob;
      updateDownload();
      if (!audio.src && currentPath()) load();
    },
    refresh() {
      audio.pause();
      audio.removeAttribute("src");
      load();
    },
    destroy() {
      destroyed = true;
      loadToken += 1;
      if (observer) observer.disconnect();
      if (unsubscribe) unsubscribe();
      try {
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
      } catch (err) {
        /* già scaricato */
      }
    },
  };
}
