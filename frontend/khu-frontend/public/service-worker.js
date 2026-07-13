/* eslint-disable no-restricted-globals */

/**
 * service-worker.js — Offline-first caching for the KHU app
 *
 * IMPORTANT FIX (previously caused blank/dark screens on normal
 * refresh after a new deployment): the app shell (HTML/JS/CSS) now
 * uses NETWORK-FIRST instead of cache-first. Create React App
 * fingerprints every build with a new filename hash (e.g.
 * main.7851b279.js -> main.a92f1c3d.js), so a stale cached index.html
 * pointing at an old, no-longer-existent JS filename produced a
 * silent crash -> blank screen, only fixable by a hard refresh that
 * bypassed the service worker entirely. Fans would have hit this on
 * every single deployment without knowing to hard-refresh.
 *
 * Strategy now:
 *  - App shell (HTML/CSS/JS)  -> network-first: always try to fetch
 *    the latest version first; only fall back to cache if genuinely
 *    offline. This means online users ALWAYS get the current build.
 *  - Standings/table data     -> network-first, falls back to cache
 *    if offline (unchanged from before)
 *  - Live match data          -> network-only (unchanged — stale live
 *    data is worse than no data)
 *
 * We also bump CACHE_VERSION on every meaningful change to this file,
 * which forces old cache buckets to be deleted on activate — the
 * previous version never actually changed, so old caches never got
 * cleaned up even when the strategy itself was supposed to do so.
 */

const CACHE_VERSION = "v2"; // bump this string whenever service-worker.js changes meaningfully
const CACHE_NAME = `khu-app-shell-${CACHE_VERSION}`;
const DATA_CACHE_NAME = `khu-app-data-${CACHE_VERSION}`;

const APP_SHELL_URLS = [
  "/",
  "/index.html",
  "/manifest.json",
  "/icon-192.png",
  "/icon-512.png",
];

// ── Listen for the "activate now" signal from serviceWorkerRegistration.js ──
// This is what lets a new deployment take over immediately instead of
// waiting for every open tab to be closed first (which could otherwise
// leave fans stuck on a stale version indefinitely).
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// ── Install: pre-cache the app shell, activate immediately ──
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL_URLS))
  );
  self.skipWaiting(); // don't wait for old tabs to close before activating
});

// ── Activate: delete ANY cache bucket that isn't this exact version ──
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
  self.clients.claim(); // take control of already-open tabs immediately
});

// ── Fetch: route requests based on type ──
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API calls to the backend — network-first, cache as fallback
  if (url.pathname.startsWith("/api/")) {
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

  // App shell / static assets (HTML, JS, CSS, icons) — NETWORK-FIRST.
  // This is the actual fix: always prefer the live network version so
  // a fresh deployment is picked up on normal refresh, not just hard
  // refresh. Cache is only used as a fallback when genuinely offline.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// ── Push notifications (unchanged) ──
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
