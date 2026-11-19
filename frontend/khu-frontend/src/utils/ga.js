// Optional Google Analytics 4. Does NOTHING unless REACT_APP_GA_ID is set at
// build time (Vercel -> Environment Variables), and never runs for browsers
// that send Do Not Track / Global Privacy Control. No ad features, no
// cross-site "signals", IP anonymised. Page views are sent per screen name,
// the same names our own cookie-free counter uses.
const GA_ID_PATTERN = /^G-[A-Z0-9]{4,20}$/;
let active = false;

export function initGA(id = process.env.REACT_APP_GA_ID, win = typeof window !== "undefined" ? window : null, doc = typeof document !== "undefined" ? document : null) {
  try {
    if (!win || !doc || !GA_ID_PATTERN.test(id || "")) return false;
    const nav = win.navigator || {};
    if (nav.doNotTrack === "1" || win.doNotTrack === "1" || nav.globalPrivacyControl === true) return false;
    if (win.__khuGaLoaded) return true; // never inject gtag.js twice
    win.__khuGaLoaded = true;
    win.dataLayer = win.dataLayer || [];
    win.gtag = function gtag() { win.dataLayer.push(arguments); }; // eslint-disable-line prefer-rest-params
    win.gtag("js", new Date());
    win.gtag("config", id, {
      send_page_view: false,
      anonymize_ip: true,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
    });
    const s = doc.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(id);
    doc.head.appendChild(s);
    active = true;
    return true;
  } catch (e) {
    return false; // analytics must never break the app
  }
}

export function gaView(view, win = typeof window !== "undefined" ? window : null) {
  try {
    if (!active || !win || typeof win.gtag !== "function" || !view) return;
    win.gtag("event", "page_view", { page_title: "KHU Live — " + view, page_path: "/" + view });
  } catch (e) { /* ignore */ }
}
