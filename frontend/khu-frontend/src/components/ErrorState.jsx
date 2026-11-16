import React from "react";

export default function ErrorState({ title, message, detail, compact }) {
  return (
    <div className="error-wrap" style={compact ? { padding: "24px 16px" } : {}}>
      <div className="error-icon">⚠️</div>
      <div className="error-title">{title}</div>
      <div className="error-sub">{message}</div>
      {detail && (
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted)", fontFamily: "monospace", background: "var(--surface)", padding: "8px 12px", borderRadius: 8 }}>
          {detail}
        </div>
      )}
      {!compact && (
        <button className="retry-btn" onClick={() => window.location.reload()}>
          Retry
        </button>
      )}
    </div>
  );
}
