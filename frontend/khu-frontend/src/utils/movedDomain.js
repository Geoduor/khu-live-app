// The app moved from khu-live-app.vercel.app to khulive.co.ke. Both addresses
// serve the same build, so anyone who still opens the old address (browser
// tab, old bookmark, an app installed from it) is sent to the new one,
// keeping the page, query and #hash they were on.
// The old service worker is deliberately NOT removed: it keeps delivering
// push notifications to people who subscribed on the old address.
export const OLD_HOST = "khu-live-app.vercel.app";
export const NEW_ORIGIN = "https://khulive.co.ke";

export function movedDomainTarget(loc) {
  if (!loc || loc.hostname !== OLD_HOST) return null;
  return NEW_ORIGIN + (loc.pathname || "/") + (loc.search || "") + (loc.hash || "");
}

// True when the page is running as an installed app (own window, no browser bar).
export function isInstalledApp(win) {
  try {
    if (win.navigator && win.navigator.standalone === true) return true; // iOS home-screen app
    return Boolean(win.matchMedia && win.matchMedia("(display-mode: standalone)").matches);
  } catch {
    return false;
  }
}
