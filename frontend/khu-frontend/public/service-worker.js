/* eslint-disable no-restricted-globals */

/**
 * service-worker.js — Offline-first caching for the KHU app
 *
 * Strategy (matches how FotMob/ESPN handle offline):
 *  - App shell (HTML/CSS/JS)  -> cache-first, so the app opens instantly offline
 *  - Standings/table data     -> network-first, falls back to cache if offline
 *                                (standings don't need to be second-fresh, but
 *                                 should still prefer live data when available)
 *  - Live match data          -> network-only (no point caching something
 *                                 that's stale by definition within seconds)
 */

const CACHE_NAME = "khu-app-shell-v1";
const DATA_CACHE_NAME = "khu-app-data-v1";

const APP_SHELL_URLS = [
  "/",
  "/index.html",
  "/manifest.json",
  "/icon-192.png",
  "/icon-512.png",
];

// ── Install: pre-cache the app shell ──
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL_URLS))
  );
  self.skipWaiting();
});

// ── Activate: clean up old cache versions ──
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME && key !== DATA_CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: route requests based on type ──
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API calls to the backend — network-first, cache as fallback
  if (url.pathname.startsWith("/api/")) {
    // Never cache live match data — it's meaningless once stale
    if (url.pathname === "/api/live") {
      event.respondWith(fetch(event.request));
      return;
    }

    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(DATA_CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // App shell / static assets — cache-first
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});

// ── Push notifications (Feature 4) ──
self.addEventListener("push", (event) => {
  let payload = { title: "KHU Update", body: "New match activity" };
  try {
    payload = event.data.json();
  } catch (e) {
    // fall back to default payload
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: payload.url || "/",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = event.notification.data || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === targetUrl && "focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});
