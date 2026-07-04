import React from "react";
import ReactDOM from "react-dom/client";
import "./App.css";
import App from "./App";
import * as serviceWorkerRegistration from "./serviceWorkerRegistration";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Register the service worker so the app works offline and can be
// installed as a PWA ("Add to Home Screen").
serviceWorkerRegistration.register();
