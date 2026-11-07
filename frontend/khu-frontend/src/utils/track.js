// Privacy-friendly usage counting: no cookies, no ids, nothing stored on the
// device. The server only adds 1 to a per-day counter for the screen name.
// Browsers that ask not to be tracked (Do Not Track / Global Privacy Control)
// are never counted.
// Same address the rest of the app uses (the Cloudflare Worker when set up, see public/edge-config.js).
// Posting straight to Render is refused once Render is locked to the Worker, which silently stopped all counting.
const EDGE = (typeof window !== "undefined" && window.KHU_EDGE) || {};
const BASE = EDGE.apiBase || process.env.REACT_APP_API_URL || "http://localhost:8000";

function refused() {
  try {
    return navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl === true;
  } catch (e) {
    return false;
  }
}

function post(path, body) {
  if (refused()) return;
  try {
    fetch(`${BASE}${path}`, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      keepalive: true,
    }).catch(() => {});
  } catch (e) { /* analytics must never break the app */ }
}

let lastView = "";
export function trackView(view) {
  if (!view || view === lastView) return;
  lastView = view;
  post("/api/analytics/hit", { view });
}

export function trackInstall() { post("/api/analytics/install"); }
export function trackSponsor(id, event) { post(`/api/sponsors/${encodeURIComponent(id)}/${event}`); }
