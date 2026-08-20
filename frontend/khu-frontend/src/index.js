import React from "react";
import ReactDOM from "react-dom/client";
import "./App.css";
import App from "./App";
import * as serviceWorkerRegistration from "./serviceWorkerRegistration";

// Apply the saved theme BEFORE React mounts, so there's no flash of
// the wrong theme on load — same value useTheme() will read, just
// applied synchronously here first.
//
// Light is the app's default theme. We only deviate from it if the
// person has explicitly picked dark mode before (stored in
// localStorage) — we no longer default to the OS's prefers-color-scheme,
// so a phone set to system dark mode still opens the app in light mode
// on first visit.
(function applyInitialTheme() {
  try {
    const stored = localStorage.getItem("khu_theme");
    if (stored === "light" || stored === "dark") {
      document.documentElement.setAttribute("data-theme", stored);
      return;
    }
  } catch {
    // localStorage unavailable — fall through to default
  }
  document.documentElement.setAttribute("data-theme", "light");
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
