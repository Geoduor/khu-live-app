import React, { useState } from "react";

/**
 * ShareButton — runs an async `onShare()` (build image + open share
 * sheet) with a busy state and a short result hint. Never triggers the
 * parent card's click (stopPropagation).
 */
export default function ShareButton({ onShare, label = "Share", className = "" }) {
  const [state, setState] = useState("idle"); // idle | busy | done | error

  const click = async (e) => {
    e.stopPropagation();
    if (state === "busy") return;
    setState("busy");
    try {
      const outcome = await onShare();
      setState(outcome === "cancelled" ? "idle" : "done");
    } catch (err) {
      setState("error");
    }
    setTimeout(() => setState("idle"), 2200);
  };

  const text = state === "busy" ? "Making image…" : state === "done" ? "✓ Ready" : state === "error" ? "Couldn't share" : `↗ ${label}`;
  return (
    <button type="button" className={`share-btn ${className}`} onClick={click} disabled={state === "busy"}>
      {text}
    </button>
  );
}
