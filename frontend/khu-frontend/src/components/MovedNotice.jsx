import React, { useState } from "react";
import { NEW_ORIGIN } from "../utils/movedDomain";

// Shown only inside an app installed from the OLD address. A page on a
// different address can never fill that app's window without the browser's
// address bar, so the honest fix is a one-time reinstall from the new address.
export default function MovedNotice({ target }) {
  const [copied, setCopied] = useState(false);
  const host = NEW_ORIGIN.replace(/^https?:\/\//, "");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(NEW_ORIGIN);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      window.prompt("Copy this link:", NEW_ORIGIN);
    }
  };
  const box = { maxWidth: 420, margin: "0 auto", padding: "48px 24px", fontFamily: "system-ui, sans-serif", color: "#1a1a1a" };
  const btn = { display: "block", width: "100%", padding: "14px 16px", margin: "10px 0", borderRadius: 12, border: "1px solid #c40000", background: "#c40000", color: "#fff", fontSize: 16, fontWeight: 700, cursor: "pointer" };
  const ghost = { ...btn, background: "transparent", color: "#c40000" };
  return (
    <div style={{ minHeight: "100vh", background: "#FBF8F7" }}>
      <div style={box} role="main">
        <h1 style={{ fontSize: 28, margin: "0 0 12px" }}>KHU Live has a new home</h1>
        <p style={{ fontSize: 17, lineHeight: 1.5 }}>
          We now live at <strong>{host}</strong>. To keep the full app (no address bar), install it once from the new address:
        </p>
        <ol style={{ fontSize: 17, lineHeight: 1.7, paddingLeft: 22 }}>
          <li>Open <strong>Chrome</strong> (or Safari on iPhone) and go to <strong>{host}</strong></li>
          <li>Tap <strong>Install</strong> (or ⋮ menu → Install app / Share → Add to Home Screen)</li>
          <li>You can then delete this old icon</li>
        </ol>
        <button style={btn} onClick={copy}>{copied ? "Copied ✓" : `Copy ${host}`}</button>
        <button style={ghost} onClick={() => window.location.replace(target)}>Continue to the new site for now</button>
        <p style={{ fontSize: 13, color: "#666", marginTop: 20 }}>Unofficial fan app. Not affiliated with the Kenya Hockey Union.</p>
      </div>
    </div>
  );
}
