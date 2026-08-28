import React from "react";
import { useInstallPrompt } from "../hooks/useInstallPrompt";

export default function InstallBanner() {
  const { canPromptInstall, showIOSInstructions, promptInstall, dismiss } = useInstallPrompt();

  if (!canPromptInstall && !showIOSInstructions) return null;

  return (
    <div className="install-banner">
      <div className="install-banner-text">
        {canPromptInstall ? (
          <>📲 Install this app for quick access — no app store needed.</>
        ) : (
          <>📲 Install this app: tap <strong>Share</strong> → <strong>Add to Home Screen</strong></>
        )}
      </div>
      <div className="install-banner-actions">
        {canPromptInstall && (
          <button className="install-banner-btn" onClick={promptInstall}>Install</button>
        )}
        <button className="install-banner-dismiss" onClick={dismiss} aria-label="Dismiss">✕</button>
      </div>
    </div>
  );
}
