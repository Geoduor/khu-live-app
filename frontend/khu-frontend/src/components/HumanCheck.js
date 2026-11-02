import React, { useEffect, useRef } from "react";

/**
 * Cloudflare Turnstile "are you human" box. Shows nothing unless a site key is set in public/edge-config.js,
 * so the app behaves exactly as before until the edge layer is switched on.
 */
export const humanCheckOn = () => !!(typeof window !== "undefined" && window.KHU_EDGE && window.KHU_EDGE.turnstileSiteKey);

export default function HumanCheck({ onToken, resetKey }) {
  const box = useRef(null);
  const widget = useRef(null);
  useEffect(() => {
    if (!humanCheckOn()) return undefined;
    let cancelled = false;
    const draw = () => {
      if (cancelled || !window.turnstile || !box.current || widget.current !== null) return;
      widget.current = window.turnstile.render(box.current, {
        sitekey: window.KHU_EDGE.turnstileSiteKey,
        callback: (t) => onToken(t),
        "expired-callback": () => onToken(""),
        "error-callback": () => onToken(""),
      });
    };
    if (window.turnstile) draw();
    else {
      window.__khuTsReady = draw;
      if (!document.getElementById("khu-ts-script")) {
        const s = document.createElement("script");
        s.id = "khu-ts-script";
        s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=__khuTsReady";
        s.async = true; s.defer = true;
        document.head.appendChild(s);
      }
    }
    return () => {
      cancelled = true;
      if (window.turnstile && widget.current !== null) { try { window.turnstile.remove(widget.current); } catch (e) { /* already gone */ } }
      widget.current = null;
    };
  }, [onToken]);
  useEffect(() => {
    if (resetKey && window.turnstile && widget.current !== null) { try { window.turnstile.reset(widget.current); } catch (e) { /* ignore */ } }
  }, [resetKey]);
  if (!humanCheckOn()) return null;
  return <div ref={box} style={{ margin: "12px 0" }} />;
}
