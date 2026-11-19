import React, { useEffect, useState } from "react";
import { needsChoice, setConsent, getConsent, resetConsent, cookiesInUse } from "../utils/consent";

// Small notice shown once, until the visitor chooses. Accept and Decline are equally easy to tap.
export default function ConsentBanner() {
  const [show, setShow] = useState(() => needsChoice());
  useEffect(() => {
    const sync = () => setShow(needsChoice());
    window.addEventListener("khu-consent-changed", sync);
    return () => window.removeEventListener("khu-consent-changed", sync);
  }, []);
  if (!show) return null;
  return (
    <div className="consent" role="dialog" aria-label="Cookie choices">
      <p className="consent-text">
        Cookies for visit counts and ads (Google)? The app works either way.{" "}
        <a href="/privacy.html" target="_blank" rel="noopener noreferrer">Privacy</a>
      </p>
      <div className="consent-btns">
        <button type="button" className="consent-btn" onClick={() => setConsent("denied")}>Decline</button>
        <button type="button" className="consent-btn consent-accept" onClick={() => setConsent("granted")}>Accept</button>
      </div>
    </div>
  );
}

// Footer line at the bottom of every screen: privacy policy + a way to change the choice later.
export function PrivacyLinks() {
  const [state, setState] = useState(() => getConsent());
  useEffect(() => {
    const sync = () => setState(getConsent());
    window.addEventListener("khu-consent-changed", sync);
    return () => window.removeEventListener("khu-consent-changed", sync);
  }, []);
  return (
    <p className="privacy-links">
      <a href="/privacy.html" target="_blank" rel="noopener noreferrer">Privacy</a>
      {cookiesInUse() ? (
        <>
          {" · "}
          <button type="button" className="link-btn" onClick={() => resetConsent()}>
            Cookie choices{state === "granted" ? " (on)" : state === "denied" ? " (off)" : ""}
          </button>
        </>
      ) : null}
    </p>
  );
}
