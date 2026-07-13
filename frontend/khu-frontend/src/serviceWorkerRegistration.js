/**
 * serviceWorkerRegistration.js
 * Registers the service worker so the app works offline and can install as a PWA.
 *
 * IMPORTANT: also handles automatic updates. Without this, a fan who
 * already has the app open/cached would need to know to hard-refresh
 * every time we ship a new deployment (see the network-first fix in
 * service-worker.js for the other half of this fix). This code
 * detects when a new service worker version has installed and is
 * waiting, activates it immediately, and reloads the page ONCE
 * automatically — so updates just... happen, with no dark screen and
 * no manual hard-refresh required.
 */

export function register() {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker
        .register("/service-worker.js")
        .then((registration) => {
          console.log("KHU Service Worker registered:", registration.scope);

          // ── Detect a new service worker version waiting to activate ──
          registration.addEventListener("updatefound", () => {
            const newWorker = registration.installing;
            if (!newWorker) return;

            newWorker.addEventListener("statechange", () => {
              if (
                newWorker.state === "installed" &&
                navigator.serviceWorker.controller
              ) {
                // A new version has installed and there's an existing
                // controller (i.e. this isn't the very first install) —
                // tell it to activate immediately rather than wait for
                // all tabs to close, which could otherwise take days.
                newWorker.postMessage({ type: "SKIP_WAITING" });
              }
            });
          });
        })
        .catch((error) => {
          console.error("Service Worker registration failed:", error);
        });

      // ── Reload the page ONCE when the new service worker takes control ──
      // This is what actually delivers the update to the user without
      // them needing to manually refresh at all, let alone hard-refresh.
      let hasReloaded = false;
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (hasReloaded) return;
        hasReloaded = true;
        window.location.reload();
      });
    });
  }
}

export function unregister() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.ready.then((registration) => {
      registration.unregister();
    });
  }
}
