import { describe, it, expect, beforeEach } from "vitest";
import { getConsent, needsChoice, applyConsent, setConsent, resetConsent, cookiesInUse, CONSENT_KEY } from "./consent";
import { initAds, adsConfigured } from "./adsense";

const GA = "G-ABC1234567";
const ADS = "ca-pub-6830892090584666";
const mkDoc = () => { const scripts = []; return { scripts, cookie: "", location: { hostname: "khulive.co.ke" }, createElement: () => ({}), head: { appendChild: (s) => scripts.push(s) } }; };
const mkWin = (nav = {}) => { const store = {}; return { navigator: nav, localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } }, dispatchEvent: () => true, location: { reload: () => { store.__reloaded = "1"; } }, store }; };

describe("consent", () => {
  let win, doc;
  beforeEach(() => { win = mkWin(); doc = mkDoc(); });

  it("asks nothing when no cookie-setting service is configured", () => {
    expect(cookiesInUse("", "")).toBe(false);
    expect(needsChoice(win, "", "")).toBe(false);
  });
  it("asks once when Analytics or AdSense is configured", () => {
    expect(needsChoice(win, GA, "")).toBe(true);
    expect(needsChoice(win, "", ADS)).toBe(true);
  });
  it("loads NOTHING from Google before the visitor chooses", () => {
    expect(applyConsent(win, doc, GA, ADS)).toBe(false);
    expect(doc.scripts.length).toBe(0);
  });
  it("loads nothing after Decline, and stops asking", () => {
    win.localStorage.setItem(CONSENT_KEY, "denied");
    expect(applyConsent(win, doc, GA, ADS)).toBe(false);
    expect(doc.scripts.length).toBe(0);
    expect(needsChoice(win, GA, ADS)).toBe(false);
  });
  it("Do Not Track / Global Privacy Control count as declined, never asked, never loaded", () => {
    for (const nav of [{ doNotTrack: "1" }, { globalPrivacyControl: true }]) {
      const w = mkWin(nav); w.localStorage.setItem(CONSENT_KEY, "granted");
      expect(getConsent(w)).toBe("denied");
      expect(needsChoice(w, GA, ADS)).toBe(false);
      expect(applyConsent(w, doc, GA, ADS)).toBe(false);
    }
    expect(doc.scripts.length).toBe(0);
  });
  it("storage that throws behaves as 'not decided' and loads nothing", () => {
    const w = { navigator: {}, localStorage: { getItem() { throw new Error("blocked"); } }, dispatchEvent: () => true };
    expect(getConsent(w)).toBe(null);
    expect(applyConsent(w, doc, GA, ADS)).toBe(false);
  });
  it("Accept loads Analytics and AdSense from Google only, once", () => {
    win.localStorage.setItem(CONSENT_KEY, "granted");
    expect(applyConsent(win, doc, GA, ADS)).toBe(true);
    const srcs = doc.scripts.map((s) => s.src);
    expect(srcs).toContain("https://www.googletagmanager.com/gtag/js?id=" + GA);
    expect(srcs).toContain("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" + ADS);
    expect(srcs.every((u) => /^https:\/\/(www\.googletagmanager\.com|pagead2\.googlesyndication\.com)\//.test(u))).toBe(true);
    applyConsent(win, doc, GA, ADS);
    expect(doc.scripts.length).toBe(srcs.length); // not loaded twice
  });
  it("revoking after Accept clears Google cookies and reloads", () => {
    win.localStorage.setItem(CONSENT_KEY, "granted");
    setConsent("denied", win, doc);
    expect(win.localStorage.getItem(CONSENT_KEY)).toBe("denied");
    expect(win.store.__reloaded).toBe("1");
  });
  it("resetConsent asks again", () => {
    win.localStorage.setItem(CONSENT_KEY, "denied");
    resetConsent(win);
    expect(needsChoice(win, GA, ADS)).toBe(true);
  });
  it("ignores junk values", () => {
    setConsent("yes please", win, doc);
    expect(getConsent(win)).toBe(null);
  });
});

describe("adsense loader", () => {
  it("rejects anything that is not a real publisher id", () => {
    for (const bad of ["", undefined, "ca-pub-1", "ca-pub-123456789012345\"><script>", "pub-6830892090584666", "G-ABC1234567"]) {
      expect(adsConfigured(bad)).toBe(false);
      expect(initAds(bad, {}, mkDoc())).toBe(false);
    }
  });
  it("injects the script with crossorigin=anonymous", () => {
    const d = mkDoc(); const w = {};
    expect(initAds(ADS, w, d)).toBe(true);
    expect(d.scripts[0].crossOrigin).toBe("anonymous");
    expect(d.scripts[0].async).toBe(true);
    expect(Array.isArray(w.adsbygoogle)).toBe(true);
  });
});
