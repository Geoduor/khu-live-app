import { useState, useEffect, useCallback } from "react";

const DISMISS_KEY = "khu_install_prompt_dismissed_at";
const DISMISS_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000; // don't re-nag for 7 days after a dismissal

function isStandaloneAlready() {
  // True if the app is already running installed (not in a browser tab) —
  // covers both the standard PWA check and iOS's older non-standard flag.
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

function isIOSSafari() {
  const ua = window.navigator.userAgent;
  const isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  // Exclude Chrome-on-iOS (CriOS) and Firefox-on-iOS (FxiOS) — they're
  // still using Safari's WebKit engine and iOS's manual "Add to Home
  // Screen" flow, but the Share-sheet steps differ enough from Safari
  // that giving Safari-specific instructions to a Chrome-on-iOS user
  // would just be confusing/wrong.
  const isSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
  return isIOS && isSafari;
}

/**
 * useInstallPrompt — cross-platform "can this device install the PWA
 * right now, and how" state.
 *
 * Android/desktop Chrome/Edge: browser fires `beforeinstallprompt`,
 * which we capture and can trigger on demand via promptInstall().
 *
 * iOS Safari: Apple has never implemented beforeinstallprompt — there
 * is no programmatic install trigger at all. The only path is the
 * user manually tapping Share → Add to Home Screen. We can't automate
 * that, only detect the platform and show instructions for it.
 *
 * Already-installed (standalone) sessions never show anything here.
 */
export function useInstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    try {
      const dismissedAt = localStorage.getItem(DISMISS_KEY);
      if (dismissedAt && Date.now() - Number(dismissedAt) < DISMISS_COOLDOWN_MS) {
        setDismissed(true);
      }
    } catch {
      // localStorage unavailable — just don't persist dismissal, no crash
    }

    const handler = (e) => {
      e.preventDefault(); // stop Chrome's automatic mini-infobar so our own banner controls the UX
      setDeferredPrompt(e);
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  const promptInstall = useCallback(async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice; // resolves once the user accepts/dismisses the native dialog
    setDeferredPrompt(null); // a captured prompt can only be used once
  }, [deferredPrompt]);

  const dismiss = useCallback(() => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      // no-op if storage is unavailable — dismissal just won't persist across sessions
    }
  }, []);

  const alreadyInstalled = isStandaloneAlready();
  const iosSafari = isIOSSafari();

  return {
    // Show the native "Install" button — only true on platforms that
    // actually fired beforeinstallprompt (Android/desktop Chrome/Edge).
    canPromptInstall: Boolean(deferredPrompt) && !alreadyInstalled && !dismissed,
    // Show manual iOS instructions instead — iOS never fires the event
    // above, so this is the only way those users find out installing
    // is even possible.
    showIOSInstructions: iosSafari && !alreadyInstalled && !dismissed,
    promptInstall,
    dismiss,
  };
}
