import { useState, useEffect } from "react";
import { teamLogoUrl } from "../api";

/**
 * TeamLogo — renders a team's crest image, falling back to a clean
 * initials avatar if the image URL is missing OR fails to actually
 * load (404, hotlink-blocked, stale/moved on KHU's site, etc.).
 *
 * Without this, a broken src just shows the browser's native "broken
 * image" icon — which reads as "the app is broken" rather than "we
 * don't have this team's logo yet."
 *
 * Reuses whatever sizing className is passed in (team-logo-sm,
 * team-profile-badge-img, scoreboard-hero-logo, etc.) so it's a
 * drop-in replacement for a plain <img> anywhere in the app.
 */
export default function TeamLogo({ src, name, className = "" }) {
  const [failed, setFailed] = useState(false);

  // Reset fallback state if the src itself changes (e.g. navigating
  // between different teams re-uses the same mounted component in some
  // lists) — otherwise a prior failure would stick even for a new,
  // perfectly valid src.
  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) {
    const initials = (name || "?")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase() || "?";

    return (
      <div
        className={`${className} team-logo-fallback`}
        title={name || ""}
        aria-label={name || "Team logo"}
      >
        {initials}
      </div>
    );
  }

  return (
    <img
      src={teamLogoUrl(src)}
      alt=""
      className={className}
      onError={() => setFailed(true)}
    />
  );
}
