/* KaosGDD Web Push service worker. This worker intentionally caches nothing. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data?.json() || {};
  } catch (_error) {
    payload = {};
  }
  const title = String(payload.title || "KaosGDD");
  const body = String(payload.body || "Something needs attention.");
  const url = String(payload.url || "/#/notifications");
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag: String(payload.tag || "kaos-notification"),
      icon: String(payload.icon || "/icons/main/android-chrome-192x192.png"),
      badge: String(payload.badge || "/icons/main/android-chrome-192x192.png"),
      data: { url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(String(event.notification.data?.url || "/#/notifications"), self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const existing = windows.find((client) => new URL(client.url).origin === self.location.origin);
      if (existing) {
        return existing.navigate(target).then(() => existing.focus());
      }
      return self.clients.openWindow(target);
    }),
  );
});
