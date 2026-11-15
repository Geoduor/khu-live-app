import React from "react";

export default function LoadingState({ message = "Loading..." }) {
  return (
    <div className="loading-wrap">
      <div className="spinner" />
      <div style={{ fontSize: 13, color: "var(--muted)" }}>{message}</div>
    </div>
  );
}
