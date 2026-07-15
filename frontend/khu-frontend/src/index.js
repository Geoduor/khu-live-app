import React from "react";
import ReactDOM from "react-dom/client";
import "./App.css";
import App from "./App";
import * as serviceWorkerRegistration from "./serviceWorkerRegistration";

// Apply the saved theme BEFORE React mounts, so there's no flash of
// the wrong theme on load — same value useTheme() will read, just
// applied synchronously here first.
(function applyInitialTheme() {
  try {
    const stored = localStorage.getItem("khu_theme");
    if (stored === "light" || stored === "dark") {
      document.documentElement.setAttribute("data-theme", stored);
      return;
    }
  } catch {
    // localStorage unavailable — fall through to OS preference
  }
  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
  document.documentElement.setAttribute("data-theme", prefersLight ? "light" : "dark");
})();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Register the service worker so the app works offline and can be
// installed as a PWA ("Add to Home Screen").
serviceWorkerRegistration.register();
