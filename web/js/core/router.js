/* RVC Portable — router di viste (senza hash, stato in settings.ui.last_view). */
import { h, clear } from "./dom.js";
import { t } from "./i18n.js";
import { btn, emptyState } from "../components/ui.js";
import { dashboardView } from "../views/dashboard.js";
import { configView } from "../views/config.js";
import { monitorView } from "../views/monitor.js";
import { modelsView } from "../views/models.js";
import { cloudView } from "../views/cloud.js";
import { advancedView } from "../views/advanced.js";
import { setupView } from "../views/setup.js";

const VIEWS = {
  dashboard: dashboardView,
  config: configView,
  monitor: monitorView,
  models: modelsView,
  cloud: cloudView,
  advanced: advancedView,
  setup: setupView,
};

export const VIEW_IDS = Object.keys(VIEWS);

let rootElement = null;
let context = null;
let onViewChange = null;
let current = null;
let currentId = null;
let navigationToken = 0;

export function initRouter(options) {
  rootElement = options.root;
  context = options.context || {};
  onViewChange = options.onViewChange || null;
}

export function currentViewId() {
  return currentId;
}

export function currentView() {
  return current ? current.view : null;
}

export async function show(id, options) {
  const view = VIEWS[id] || VIEWS.dashboard;
  const token = ++navigationToken;
  if (current && typeof current.cleanup === "function") {
    try {
      current.cleanup();
    } catch (err) {
      console.error("cleanup vista fallito", err);
    }
  }
  current = null;
  currentId = view.id;
  clear(rootElement);
  const section = h("section", {
    class: "view view-" + view.id,
    id: "view-" + view.id,
    "aria-labelledby": "view-title-" + view.id,
  });
  rootElement.appendChild(section);
  document.title = t(view.titleKey || "app.title") + " — " + t("app.name");
  if (onViewChange) {
    try {
      onViewChange(view.id);
    } catch (err) {
      console.error(err);
    }
  }
  let cleanup = null;
  try {
    cleanup = await view.mount(section, context, options || {});
  } catch (err) {
    console.error("mount vista fallito", view.id, err);
    section.appendChild(
      emptyState({
        iconName: "alert",
        title: t("app.fatalTitle"),
        text: String((err && err.message) || err),
        actions: [
          btn(t("app.reload"), {
            variant: "primary",
            iconName: "refresh",
            onClick: () => window.location.reload(),
          }),
        ],
      })
    );
  }
  if (token !== navigationToken) return null;
  current = { id: view.id, view, cleanup: typeof cleanup === "function" ? cleanup : null };
  const heading = section.querySelector("h1");
  if (heading) {
    try {
      heading.focus({ preventScroll: true });
    } catch (err) {
      /* focus non disponibile */
    }
  }
  try {
    window.scrollTo({ top: 0, behavior: "auto" });
  } catch (err) {
    /* scrollTo non disponibile */
  }
  return current;
}

export function refreshCurrentView() {
  if (currentId) return show(currentId);
  return Promise.resolve(null);
}

export function destroyRouter() {
  if (current && typeof current.cleanup === "function") {
    try {
      current.cleanup();
    } catch (err) {
      console.error(err);
    }
  }
  current = null;
  currentId = null;
}
