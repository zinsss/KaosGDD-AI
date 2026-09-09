(function () {
  "use strict";

  const state = {
    checked: false,
    loading: false,
    saving: false,
    testing: false,
    supported: false,
    installed: true,
    enabled: false,
    configured: false,
    permission: typeof Notification === "undefined" ? "default" : Notification.permission,
    subscriptionId: "",
    error: "",
  };

  function isMain() {
    return window.location.hostname !== "family.kaosgdd.net";
  }

  function isIos() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
  }

  function isInstalled() {
    return !isIos() || window.navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
  }

  function supported() {
    return isMain() && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function decodeApplicationKey(value) {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const raw = window.atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (character) => character.charCodeAt(0));
  }

  async function responseJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }

  async function subscriptionId(subscription) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(subscription.endpoint));
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 24);
  }

  async function registration() {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    return navigator.serviceWorker.ready;
  }

  async function currentSubscription() {
    if (!supported()) return null;
    const worker = await registration();
    return worker.pushManager.getSubscription();
  }

  async function refresh() {
    if (!isMain() || state.loading) return state;
    state.loading = true;
    state.error = "";
    state.supported = supported();
    state.installed = isInstalled();
    state.permission = typeof Notification === "undefined" ? "default" : Notification.permission;
    try {
      if (!state.supported) return state;
      const [config, subscription] = await Promise.all([
        fetch("/api/web-push/config", { credentials: "same-origin", cache: "no-store" }).then(responseJson),
        currentSubscription(),
      ]);
      state.configured = Boolean(config.enabled && config.configured && config.publicKey);
      state.enabled = Boolean(subscription);
      state.subscriptionId = subscription ? await subscriptionId(subscription) : "";
    } catch (error) {
      state.error = error.message || "Web Push unavailable";
    } finally {
      state.checked = true;
      state.loading = false;
    }
    return state;
  }

  async function enable() {
    if (!supported()) throw new Error("Web Push is not supported on this device.");
    if (!isInstalled()) throw new Error("Add KaosGDD to the Home Screen first.");
    state.saving = true;
    state.error = "";
    try {
      const permission = await Notification.requestPermission();
      state.permission = permission;
      if (permission !== "granted") throw new Error("Notification permission was not granted.");
      const config = await fetch("/api/web-push/config", {
        credentials: "same-origin",
        cache: "no-store",
      }).then(responseJson);
      if (!config.enabled || !config.publicKey) throw new Error("Web Push is not configured on the server.");
      const worker = await registration();
      const existing = await worker.pushManager.getSubscription();
      const subscription = existing || await worker.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeApplicationKey(config.publicKey),
      });
      const result = await fetch("/api/web-push/subscriptions", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subscription: subscription.toJSON() }),
      }).then(responseJson);
      state.subscriptionId = String(result.subscription?.id || await subscriptionId(subscription));
      state.enabled = true;
      state.configured = true;
      state.checked = true;
    } catch (error) {
      state.error = error.message || "Could not enable Web Push.";
      throw error;
    } finally {
      state.saving = false;
    }
    return state;
  }

  async function disable() {
    state.saving = true;
    state.error = "";
    try {
      const subscription = await currentSubscription();
      const id = state.subscriptionId || (subscription ? await subscriptionId(subscription) : "");
      if (id) {
        await fetch(`/api/web-push/subscriptions/${encodeURIComponent(id)}`, {
          method: "DELETE",
          credentials: "same-origin",
        }).then(responseJson);
      }
      if (subscription) await subscription.unsubscribe();
      state.enabled = false;
      state.subscriptionId = "";
      state.checked = true;
    } catch (error) {
      state.error = error.message || "Could not disable Web Push.";
      throw error;
    } finally {
      state.saving = false;
    }
    return state;
  }

  async function test() {
    state.testing = true;
    state.error = "";
    try {
      const result = await fetch("/api/web-push/test", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subscriptionId: state.subscriptionId }),
      }).then(responseJson);
      return result;
    } catch (error) {
      state.error = error.message || "Could not send test notification.";
      throw error;
    } finally {
      state.testing = false;
    }
  }

  if (isMain() && "serviceWorker" in navigator) {
    window.addEventListener("load", () => registration().catch(() => {}), { once: true });
  }

  window.KAOS_WEB_PUSH = { state, refresh, enable, disable, test };
})();
