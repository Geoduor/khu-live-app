// Cookie consent for the two optional Google services (Analytics, AdSense).
// Nothing from Google is loaded until the visitor taps Accept. A browser that
// sends Do Not Track / Global Privacy Control counts as having declined, so it
// is never asked and nothing is loaded. The choice lives only in this browser.
import { initGA } from "./ga";
import { initAds, adsConfigured } from "./adsense";

export const CONSENT_KEY = "khu_consent_v1";
const GA_ID_PATTERN = /^G-[A-Z0-9]{4,20}$/;

function optedOutByBrowser(win) {
  const nav = (win && win.navigator) || {};
  return nav.doNotTrack === "1" || (win && win.doNotTrack === "1") || nav.globalPrivacyControl === true;
}

/** "granted" | "denied" | null (not decided yet) */
export function getConsent(win = typeof window !== "undefined" ? window : null) {
  try {
    if (!win) return "denied";
    if (optedOutByBrowser(win)) return "denied";
    const v = win.localStorage.getItem(CONSENT_KEY);
    return v === "granted" || v === "denied" ? v : null;
  } catch (e) {
    return null; // storage blocked: behave as "not decided" -> nothing loads
  }
}

/** True only when something that sets cookies is actually configured for this build. */
export function cookiesInUse(gaId = process.env.REACT_APP_GA_ID, adsId = process.env.REACT_APP_ADSENSE_ID) {
  return GA_ID_PATTERN.test(gaId || "") || adsConfigured(adsId);
}

/** Should the banner be shown right now? */
export function needsChoice(win = typeof window !== "undefined" ? window : null, gaId, adsId) {
  return !!win && cookiesInUse(gaId, adsId) && getConsent(win) === null;
}

/** Load the optional Google services — only if consent was granted. */
export function applyConsent(win = typeof window !== "undefined" ? window : null, doc = typeof document !== "undefined" ? document : null, gaId, adsId) {
  if (getConsent(win) !== "granted") return false;
  initGA(gaId === undefined ? process.env.REACT_APP_GA_ID : gaId, win, doc);
  initAds(adsId === undefined ? process.env.REACT_APP_ADSENSE_ID : adsId, win, doc);
  return true;
}

export function setConsent(value, win = typeof window !== "undefined" ? window : null, doc = typeof document !== "undefined" ? document : null) {
  if (value !== "granted" && value !== "denied") return;
  const before = getConsent(win);
  try { win.localStorage.setItem(CONSENT_KEY, value); } catch (e) { /* ignore */ }
  if (value === "granted") {
    applyConsent(win, doc);
  } else if (before === "granted") {
    // Scripts already running can't be unloaded: remove Google's cookies and reload clean.
    clearGoogleCookies(doc);
    try { win.location.reload(); } catch (e) { /* ignore */ }
  }
  try { win.dispatchEvent(new Event("khu-consent-changed")); } catch (e) { /* ignore */ }
}

export function resetConsent(win = typeof window !== "undefined" ? window : null) {
  try { win.localStorage.removeItem(CONSENT_KEY); } catch (e) { /* ignore */ }
  try { win.dispatchEvent(new Event("khu-consent-changed")); } catch (e) { /* ignore */ }
}

function clearGoogleCookies(doc) {
  try {
    const host = (doc.location && doc.location.hostname) || "";
    const parts = host.split(".");
    const domains = ["", host, "." + host, parts.length > 2 ? "." + parts.slice(-2).join(".") : ""];
    for (const c of (doc.cookie || "").split(";")) {
      const name = c.split("=")[0].trim();
      if (!/^(_ga|_gid|_gat|__gads|__gpi|__eoi|FCNEC|_gcl_)/.test(name)) continue;
      for (const d of domains) doc.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/` + (d ? `; domain=${d}` : "");
    }
  } catch (e) { /* ignore */ }
}
