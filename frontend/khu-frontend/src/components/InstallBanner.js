import React, { useState } from "react";
import { useInstallPrompt } from "../hooks/useInstallPrompt";

const APP_URL = (process.env.REACT_APP_PUBLIC_URL || "https://khu-live-app.vercel.app").replace(/\/+$/, "");

export default function InstallBanner() {
  const {
    canPromptInstall, showIOSInstructions, showOpenInBrowser, showIOSOpenInSafari,
    isIOS, promptInstall, dismiss,
  } = useInstallPrompt();
  const [copied, setCopied] = useState(false);

  if (!canPromptInstall && !showIOSInstructions && !showOpenInBrowser && !showIOSOpenInSafari) return null;

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(APP_URL);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      window.prompt("Copy this link:", APP_URL);
    }
  };

  let text;
  if (canPromptInstall) {
    text = <>📲 Install KHU Live on your phone — free, no app store needed.</>;
  } else if (showIOSInstructions) {
    text = <>📲 Install: tap <strong>Share</strong> <span aria-hidden="true">⬆️</span> then <strong>Add to Home Screen</strong></>;
  } else if (showIOSOpenInSafari) {
    text = <>📲 To install on iPhone, open this page in <strong>Safari</strong>, then tap Share → Add to Home Screen.</>;
  } else {
    text = <>📲 To install, open this link in <strong>{isIOS ? "Safari" : "Chrome"}</strong> (tap the ⋮ or share menu → "Open in browser").</>;
  }

  return (
    <div className="install-banner" role="region" aria-label="Install the app">
      <div className="install-banner-text">{text}</div>
      <div className="install-banner-actions">
        {canPromptInstall && (
          <button className="install-banner-btn" onClick={promptInstall}>Install</button>
        )}
        {(showOpenInBrowser || showIOSOpenInSafari) && (
          <button className="install-banner-btn" onClick={copyLink}>{copied ? "Copied ✓" : "Copy link"}</button>
        )}
        <a className="install-banner-btn install-banner-link" href="/install.html">Help</a>
        <button className="install-banner-dismiss" onClick={dismiss} aria-label="Dismiss">✕</button>
      </div>
    </div>
  );
}
