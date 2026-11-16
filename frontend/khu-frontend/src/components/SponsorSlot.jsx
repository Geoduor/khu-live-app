import React, { useEffect, useRef, useState } from "react";
import { getSponsors, sponsorLogoUrl } from "../api";
import { trackSponsor } from "../utils/track";

// One request per page load, shared by every slot on screen.
let sponsorsPromise = null;
const counted = new Set(); // sponsors whose view was already counted this page load

/** A single, clearly labelled sponsor card. Renders nothing when no sponsor is live. */
export default function SponsorSlot() {
  const [sponsor, setSponsor] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    let alive = true;
    if (!sponsorsPromise) sponsorsPromise = getSponsors().catch(() => ({ sponsors: [] }));
    sponsorsPromise.then((d) => {
      const list = d?.sponsors || [];
      if (alive && list.length) setSponsor(list[Math.floor(Math.random() * list.length)]);
    });
    return () => { alive = false; };
  }, []);

  // Count a view only once at least half the card has actually been on screen.
  useEffect(() => {
    if (!sponsor || counted.has(sponsor.id) || !ref.current) return undefined;
    const count = () => { counted.add(sponsor.id); trackSponsor(sponsor.id, "impression"); };
    if (typeof IntersectionObserver === "undefined") { count(); return undefined; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { count(); io.disconnect(); }
    }, { threshold: 0.5 });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [sponsor]);

  if (!sponsor) return null;
  return (
    <a
      ref={ref}
      className="sponsor-slot"
      href={sponsor.link_url}
      target="_blank"
      rel="noopener noreferrer sponsored"
      onClick={() => trackSponsor(sponsor.id, "click")}
      aria-label={`Sponsored: ${sponsor.name}`}
    >
      <span className="sponsor-tag">Sponsored</span>
      <span className="sponsor-body">
        {sponsor.has_logo && <img className="sponsor-logo" src={sponsorLogoUrl(sponsor.id)} alt="" loading="lazy" />}
        <span className="sponsor-text">
          <span className="sponsor-name">{sponsor.name}</span>
          {sponsor.tagline && <span className="sponsor-tagline">{sponsor.tagline}</span>}
        </span>
      </span>
    </a>
  );
}
