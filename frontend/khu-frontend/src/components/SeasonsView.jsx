import React, { useEffect, useState } from "react";
import { getHonours, getSeason } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";

/** Past seasons: roll of honour, then the final tables of a chosen season. */
export default function SeasonsView() {
  const [honours, setHonours] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState("");
  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    let alive = true;
    getHonours()
      .then((d) => alive && setHonours(d.seasons || []))
      .catch(() => alive && setError("Could not load past seasons. Please try again."));
    return () => { alive = false; };
  }, []);

  const openSeason = (label) => {
    if (open === label) { setOpen(""); setDetail(null); return; }
    setOpen(label);
    setDetail(null);
    setLoadingDetail(true);
    getSeason(label)
      .then((d) => setDetail(d))
      .catch(() => setDetail({ error: true }))
      .finally(() => setLoadingDetail(false));
  };

  if (error) return <ErrorState title="Something went wrong" message={error} compact />;
  if (!honours) return <LoadingState message="Loading past seasons..." />;
  if (!honours.length) {
    return (
      <ErrorState
        title="No past seasons yet"
        message="Finished seasons are saved here as permanent records: final tables and champions. Check back after the season ends."
        compact
      />
    );
  }

  return (
    <div className="seasons">
      {honours.map((s) => (
        <div key={s.label} className="season-card">
          <button className="season-head" onClick={() => openSeason(s.label)} aria-expanded={open === s.label}>
            <span className="season-title">{s.title || s.label}</span>
            <span className="season-chev">{open === s.label ? "▲" : "▼"}</span>
          </button>
          {s.champions.length > 0 && (
            <ul className="champ-list">
              {s.champions.map((c) => (
                <li key={c.short + c.league}>
                  <span className="champ-league">{c.league}</span>
                  <span className="champ-team">🏆 {c.champion}</span>
                </li>
              ))}
            </ul>
          )}
          {open === s.label && (
            loadingDetail ? <LoadingState message="Loading season..." /> :
            detail?.error ? <ErrorState title="Could not load this season" message="Please try again." compact /> :
            detail && (
              <div className="season-tables">
                {(detail.data?.leagues || []).map((lg) => (
                  <div key={lg.short + lg.league}>
                    <div className="season-league">{lg.league}</div>
                    <table className="season-table">
                      <thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th></tr></thead>
                      <tbody>
                        {(lg.standings || []).map((r, i) => (
                          <tr key={i}>
                            <td>{r.position ?? i + 1}</td><td className="st-team">{r.team}</td>
                            <td>{r.played}</td><td>{r.won}</td><td>{r.drawn}</td><td>{r.lost}</td>
                            <td>{r.goal_diff}</td><td><strong>{r.points}</strong></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
                {!(detail.data?.leagues || []).length && (
                  <div className="archive-count">This season has no saved tables.</div>
                )}
              </div>
            )
          )}
        </div>
      ))}
    </div>
  );
}
