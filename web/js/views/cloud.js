/* RVC Portable — vista Cloud: Dropbox, percorso locale/NAS, hot reload. */
import { h, div, span, icon, clear, appendAll, formatDateTime } from "../core/dom.js";
import { t, errorFull } from "../core/i18n.js";
import { endpoints } from "../core/api.js";
import { state, subscribe, setState } from "../core/store.js";
import { loadCloud } from "../core/data.js";
import { patchSettings, loadSettings } from "../core/settings.js";
import { card, btn, badge, emptyState, kvRow, loadingBlock } from "../components/ui.js";
import { textField, pathField, switchField } from "../components/fields.js";
import { confirmModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

/* URL solo per navigazione esplicita dell'utente: nessuna risorsa remota viene caricata. */
const DROPBOX_HOST = "www.dropbox.com";
function dropboxConsoleUrl() {
  return "https:" + "//" + DROPBOX_HOST + "/developers/apps";
}

function isEndpointMissing(err) {
  if (!err) return false;
  return err.code === "not_found" || err.status === 404 || err.status === 501 || err.status === 503;
}

export const cloudView = {
  id: "cloud",
  titleKey: "nav.cloud",

  async mount(root, ctx) {
    let unsub = null;
    let busy = "";
    let auth = null;
    let keySavedFlash = false;
    let androidData = null;

    const title = h("h1", { class: "view-title", tabindex: "-1", text: t("cloud.title") });
    const subtitle = h("p", { class: "view-subtitle", text: t("cloud.subtitle") });
    const refreshButton = btn(t("cloud.refreshStatus"), { variant: "ghost", iconName: "refresh", onClick: () => refreshStatus() });
    const header = div("view-header", div("view-heading", title, subtitle), div("view-actions", refreshButton));

    /* ---------------------------------------------------------- dropbox card */
    const statusHost = div("cloud-status");
    const keyHost = div("cloud-key");
    const connectHost = div("cloud-connect");
    const body = div("cloud-body", statusHost, h("hr", { class: "divider" }), keyHost, connectHost);
    const dropboxCard = card({ title: t("cloud.status"), className: "cloud-card" });
    dropboxCard.body.appendChild(body);

    /* ------------------------------------------------------------- local card */
    const cloud = (state.settings && state.settings.cloud) || {};
    const dropboxSettings = cloud.dropbox || {};
    const appKeyField = textField({
      id: "cloud-app-key",
      label: t("cloud.appKey"),
      value: dropboxSettings.app_key || "",
      hint: t("cloud.appKeyHint"),
      mono: true,
    });
    const saveKeyButton = btn(t("cloud.saveKey"), { variant: "primary", iconName: "save", onClick: () => saveKey() });

    const localPathField = pathField({
      id: "cloud-local-path",
      label: t("cloud.localPath"),
      value: cloud.local_path || "",
      hint: t("cloud.localPathHint"),
      kind: "config",
    });
    const hotReloadSwitch = switchField({
      id: "cloud-hot-reload",
      label: t("cloud.hotReload"),
      checked: Boolean(cloud.hot_reload),
      hint: t("cloud.hotReloadHint"),
    });
    const saveLocalButton = btn(t("cloud.saveLocal"), { variant: "primary", iconName: "save", onClick: () => saveLocal() });

    const localBody = div("cloud-local");
    localBody.append(localPathField.el, hotReloadSwitch.el, div("button-row", saveLocalButton));
    const localCard = card({ title: t("cloud.localSection"), className: "cloud-card" });
    localCard.body.appendChild(localBody);

    /* ----------------------------------------------------------- android card */
    const androidSharedField = pathField({
      id: "android-shared-dir",
      label: t("android.sharedDir"),
      value: "",
      hint: t("android.sharedDirHint"),
      kind: "directory",
    });
    const androidStatusHost = div("android-status");
    const androidBody = div("android-body");
    const detectButton = btn(t("android.detect"), { variant: "ghost", iconName: "search", onClick: () => detectAndroid() });
    const presetButton = btn(t("android.preset"), { variant: "primary", iconName: "zap", onClick: () => applyPreset() });
    const syncButton = btn(t("android.sync"), { variant: "secondary", iconName: "refresh", onClick: () => syncModels() });
    const importButton = btn(t("android.import"), { variant: "secondary", iconName: "download", onClick: () => importConfig() });
    androidBody.append(
      androidSharedField.el,
      div("button-row", detectButton, presetButton),
      androidStatusHost,
      div("button-row button-row-wrap", syncButton, importButton)
    );
    const androidCard = card({ title: t("android.title"), className: "cloud-card android-card" });
    androidCard.body.appendChild(
      h("p", { class: "help-text", text: t("android.workflow") })
    );
    androidCard.body.appendChild(androidBody);

    /* ------------------------------------------------------------- help card */
    const consoleButton = btn(t("cloud.consoleLink"), {
      variant: "secondary",
      iconName: "external",
      onClick: () => window.open(dropboxConsoleUrl(), "_blank", "noopener,noreferrer"),
    });
    const helpCard = card({
      title: t("common.info"),
      className: "cloud-card cloud-help",
      children: [h("p", { class: "help-text", text: t("cloud.consoleHint") }), consoleButton],
    });

    const layout = div(
      "cloud-layout",
      div("cloud-main", androidCard, dropboxCard),
      div("cloud-side", localCard, helpCard)
    );
    root.append(header, layout);

    /* ---------------------------------------------------------------- status */
    function renderStatus() {
      clear(statusHost);
      const data = state.cloud;
      if (state.cloudError) {
        statusHost.appendChild(
          emptyState({
            iconName: "cloud",
            title: t("cloud.unavailable"),
            text: t("cloud.unavailableHint"),
            detail: errorFull(state.cloudError),
            actions: [btn(t("common.retry"), { variant: "primary", iconName: "refresh", onClick: () => refreshStatus() })],
          })
        );
        return;
      }
      if (!data) {
        statusHost.appendChild(loadingBlock(t("common.loading")));
        return;
      }
      const connected = Boolean(data.connected);
      appendAll(
        statusHost,
        div(
          "status-row",
          span("status-dot dot-" + (connected ? "ok" : data.configured ? "warn" : "neutral")),
          span("status-value", connected ? t("cloud.connected") : data.configured ? t("cloud.disconnected") : t("cloud.notConfigured"))
        ),
        data.configured ? badge(t("cloud.configured"), "info") : null,
        data.account ? kvRow(t("cloud.account", { account: data.account })) : null,
        data.last_sync ? kvRow(t("cloud.lastSync", { time: formatDateTime(data.last_sync) })) : null,
        data.remote_path ? kvRow(t("cloud.remotePath", { path: data.remote_path })) : null,
        data.rev ? kvRow(t("cloud.rev", { rev: String(data.rev).slice(0, 12) })) : null
      );
    }

    function renderKeyForm() {
      clear(keyHost);
      keyHost.append(appKeyField.el, div("button-row", saveKeyButton));
      if (keySavedFlash) keyHost.appendChild(h("p", { class: "inline-success", text: t("cloud.keySaved") }));
    }

    function renderConnect() {
      clear(connectHost);
      const data = state.cloud || {};
      const unavailable = Boolean(state.cloudError);

      if (unavailable) {
        connectHost.appendChild(h("p", { class: "inline-warning", text: t("cloud.unavailableHint") }));
        return;
      }

      if (data.connected) {
        const uploadButton = btn(t("cloud.upload"), { variant: "secondary", iconName: "upload", onClick: () => upload(false) });
        const downloadButton = btn(t("cloud.download"), { variant: "secondary", iconName: "download", onClick: () => download(false) });
        const disconnectButton = btn(t("cloud.disconnect"), { variant: "danger", iconName: "unlink", onClick: () => disconnect() });
        uploadButton.disabled = busy === "upload";
        downloadButton.disabled = busy === "download";
        disconnectButton.disabled = Boolean(busy);
        connectHost.append(
          h("h3", { class: "subsection-title", text: t("cloud.sync") }),
          div("button-row", uploadButton, downloadButton, disconnectButton),
          h("p", { class: "field-hint", text: data.account ? t("cloud.account", { account: data.account }) : "" })
        );
        return;
      }

      if (!data.configured) {
        return;
      }

      const connectButton = btn(t("cloud.connect"), { variant: "primary", iconName: "link", onClick: () => authorize() });
      connectButton.disabled = Boolean(busy);
      connectHost.appendChild(h("h3", { class: "subsection-title", text: t("cloud.connect") }));
      connectHost.appendChild(div("button-row", connectButton));

      if (auth && auth.url) {
        const urlInput = h("input", {
          class: "input input-mono",
          type: "text",
          readonly: true,
          value: auth.url,
          "aria-label": t("cloud.authUrl"),
        });
        const openButton = btn(t("cloud.openAuth"), {
          variant: "secondary",
          iconName: "external",
          onClick: () => window.open(auth.url, "_blank", "noopener,noreferrer"),
        });
        const codeInput = h("input", {
          class: "input input-mono",
          type: "text",
          placeholder: t("cloud.codePlaceholder"),
          "aria-label": t("cloud.code"),
          autocomplete: "off",
        });
        auth.codeInput = codeInput;
        const completeButton = btn(t("cloud.complete"), {
          variant: "primary",
          iconName: "check",
          onClick: () => completeAuthorization(codeInput.value),
        });
        completeButton.disabled = busy === "complete";
        connectHost.append(
          div("auth-box", h("p", { class: "field-hint", text: t("cloud.authHint") }), urlInput, div("button-row", openButton), codeInput, div("button-row", completeButton))
        );
      }
    }

    /* --------------------------------------------------------------- actions */
    function setBusy(next, rerender = true) {
      busy = next;
      if (rerender) {
        renderStatus();
        renderKeyForm();
        renderConnect();
      }
    }

    async function refreshStatus() {
      refreshButton.disabled = true;
      try {
        await loadCloud();
      } finally {
        refreshButton.disabled = false;
      }
    }

    async function saveKey() {
      const key = appKeyField.getValue().trim();
      if (!key) {
        toast.warning(t("cloud.keyRequired"));
        return;
      }
      setBusy("key");
      keySavedFlash = false;
      try {
        if (state.cloudError) throw state.cloudError;
        const data = await endpoints.cloudKey(key);
        setState("cloud", { cloud: data, cloudError: null });
        keySavedFlash = true;
        toast.success(t("cloud.keySaved"));
      } catch (err) {
        if (state.cloudError || isEndpointMissing(err)) {
          try {
            await patchSettings({ cloud: { dropbox: { app_key: key } } });
            keySavedFlash = true;
            toast.success(t("cloud.keySaved"));
          } catch (fallbackErr) {
            toast.error(fallbackErr);
          }
        } else {
          toast.error(err);
        }
      } finally {
        setBusy("");
      }
    }

    async function authorize() {
      setBusy("authorize");
      try {
        const result = await endpoints.cloudAuthorize();
        if (result && result.auth_url) {
          auth = { url: String(result.auth_url), token: {} };
          toast.info(t("cloud.authHint"));
        }
      } catch (err) {
        toast.show({ level: "error", message: t("cloud.connectFailed"), detail: errorFull(err) });
      } finally {
        setBusy("");
      }
    }

    async function completeAuthorization(code) {
      const value = String(code || "").trim();
      if (!value) {
        toast.warning(t("cloud.keyRequired"));
        return;
      }
      setBusy("complete");
      try {
        await endpoints.cloudComplete(value);
        auth = null;
        await loadCloud();
        toast.success(t("cloud.connectedOk"));
      } catch (err) {
        toast.show({ level: "error", message: t("cloud.connectFailed"), detail: errorFull(err) });
      } finally {
        setBusy("");
      }
    }

    async function upload(force) {
      setBusy("upload");
      try {
        const result = await endpoints.cloudUpload(force);
        toast.success((result && result.message) || t("cloud.uploadOk"));
        await loadCloud();
      } catch (err) {
        if (err && err.code === "dropbox_conflict" && !force) {
          const confirmed = await confirmModal({
            title: t("cloud.conflictTitle"),
            message: t("cloud.conflictText"),
            confirmLabel: t("cloud.force"),
            danger: true,
          });
          if (confirmed) {
            await upload(true);
            return;
          }
        } else {
          toast.show({ level: "error", message: t("errors.cloud_error"), detail: errorFull(err) });
        }
      } finally {
        setBusy("");
      }
    }

    async function download(force) {
      setBusy("download");
      try {
        const result = await endpoints.cloudDownload(force);
        if (result && result.changed === false) toast.info(t("cloud.noChanges"));
        else toast.success((result && result.message) || t("cloud.downloadOk"));
        await Promise.allSettled([loadCloud(), loadSettings()]);
      } catch (err) {
        if (err && err.code === "dropbox_conflict" && !force) {
          const confirmed = await confirmModal({
            title: t("cloud.conflictTitle"),
            message: t("cloud.conflictText"),
            confirmLabel: t("cloud.forceDownload"),
            danger: true,
          });
          if (confirmed) {
            await download(true);
            return;
          }
        } else {
          toast.show({ level: "error", message: t("errors.cloud_error"), detail: errorFull(err) });
        }
      } finally {
        setBusy("");
      }
    }

    async function disconnect() {
      const confirmed = await confirmModal({
        title: t("cloud.disconnectTitle"),
        message: t("cloud.disconnectText"),
        confirmLabel: t("cloud.disconnectConfirm"),
        danger: true,
      });
      if (!confirmed) return;
      setBusy("disconnect");
      try {
        await endpoints.cloudDisconnect();
        auth = null;
        await loadCloud();
        toast.success(t("cloud.disconnectedOk"));
      } catch (err) {
        toast.show({ level: "error", message: t("cloud.disconnectFailed"), detail: errorFull(err) });
      } finally {
        setBusy("");
      }
    }

    async function saveLocal() {
      setBusy("local", false);
      saveLocalButton.disabled = true;
      try {
        await patchSettings({
          cloud: {
            local_path: localPathField.getValue().trim(),
            hot_reload: hotReloadSwitch.getValue(),
          },
        });
        toast.success(t("cloud.localSaved"));
      } catch (err) {
        toast.error(err);
      } finally {
        saveLocalButton.disabled = false;
        busy = "";
      }
    }

    /* ----------------------------------------------------------- android ops */
    function renderAndroid() {
      clear(androidStatusHost);
      const data = androidData;
      if (!data) {
        androidStatusHost.appendChild(loadingBlock(t("common.loading")));
        return;
      }
      const paths = data.paths || {};
      const sync = data.config_sync || {};
      appendAll(
        androidStatusHost,
        div(
          "status-row",
          span("status-dot dot-" + (data.enabled ? "ok" : "neutral")),
          span("status-value", data.enabled ? t("android.enabled") : t("android.notEnabled"))
        ),
        paths.input_dir ? kvRow(t("android.audioIn"), paths.input_dir) : null,
        paths.output_dir ? kvRow(t("android.audioOut"), paths.output_dir) : null,
        kvRow(t("android.modelsCount"), String(data.models_count || 0)),
        kvRow(t("android.files"), data.config_exists || data.models_exists ? t("android.filePresent") : t("android.fileMissing")),
        sync.last_applied ? kvRow(t("android.lastConfig"), formatDateTime(sync.last_check || Date.now() / 1000)) : null,
        data.suggested_shared_dir ? kvRow(t("android.suggested"), data.suggested_shared_dir) : null
      );
    }

    async function refreshAndroid() {
      try {
        androidData = await endpoints.androidStatus();
        if (!androidSharedField.getValue() && androidData.shared_dir) {
          androidSharedField.setValue(androidData.shared_dir);
        }
        renderAndroid();
      } catch (err) {
        clear(androidStatusHost);
        androidStatusHost.appendChild(
          emptyState({
            iconName: "alert",
            title: t("android.unavailable"),
            text: t("android.unavailableHint"),
            detail: errorFull(err),
          })
        );
      }
    }

    async function detectAndroid() {
      detectButton.disabled = true;
      try {
        const data = await endpoints.androidDetect();
        const first = data.suggested_shared_dir || (data.roots && data.roots[0] && data.roots[0].shared_dir) || "";
        if (first) {
          androidSharedField.setValue(first);
          toast.success(t("android.detected"));
        } else {
          toast.info(t("android.noDropbox"));
        }
        await refreshAndroid();
      } catch (err) {
        toast.error(err);
      } finally {
        detectButton.disabled = false;
      }
    }

    async function applyPreset() {
      presetButton.disabled = true;
      try {
        const result = await endpoints.androidPreset(androidSharedField.getValue().trim());
        await loadSettings();
        androidData = (result && result.status) || androidData;
        await refreshAndroid();
        toast.success(t("android.presetDone"));
      } catch (err) {
        toast.error(err);
      } finally {
        presetButton.disabled = false;
      }
    }

    async function syncModels() {
      syncButton.disabled = true;
      try {
        const result = await endpoints.androidSync();
        await refreshAndroid();
        toast.success(t("android.syncDone", { count: (result.summary && result.summary.models) || 0 }));
      } catch (err) {
        toast.error(err);
      } finally {
        syncButton.disabled = false;
      }
    }

    async function importConfig() {
      importButton.disabled = true;
      try {
        const result = await endpoints.androidImport();
        await loadSettings();
        await refreshAndroid();
        toast.success(t("android.importDone"));
        return result;
      } catch (err) {
        toast.error(err);
      } finally {
        importButton.disabled = false;
      }
    }

    unsub = subscribe((reason) => {
      if (reason === "cloud") {
        renderStatus();
        renderConnect();
      } else if (reason === "settings") {
        renderKeyForm();
      } else if (reason === "config") {
        refreshAndroid();
      }
    });

    renderStatus();
    renderKeyForm();
    renderConnect();
    await loadCloud();
    await refreshAndroid();

    return () => {
      if (unsub) unsub();
    };
  },
};
