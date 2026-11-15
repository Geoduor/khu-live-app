import React, { useState, useEffect } from "react";
import { getTeamProfile } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";
import TeamLogo from "./TeamLogo";
import { PlayerAvatar } from "./PlayerProfile";

// "2026-11-28 16:00" -> { day: "2026-11-28", time: "16:00" }. Anything that
// doesn't look like that is shown untouched (day only).
function splitDateTime(s) {
  const str = String(s || "");
  const m = str.match(/^(.*?)[\sT]+(\d{1,2}:\d{2})$/);
  return m ? { day: m[1], time: m[2] } : { day: str, time: "" };
}

// Everything below renders API text as React text nodes only (never HTML).
export default function TeamProfile({ teamUrl, teamName, league, onBack, onOpenTeam, onOpenPlayer, isFavorite, toggleFavorite }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("matches");

  useEffect(() => {
    setLoading(true);
    setData(null);
    setTab("matches");
    let alive = true;
    getTeamProfile(teamUrl, teamName, league)
      .then((d) => alive && setData(d))
      .catch(() => alive && setData({ error: "Could not load team profile" }))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [teamUrl, teamName, league]);

  const squad = data?.squad || [];
  const upcoming = data?.upcoming_fixtures || [];
  const results = data?.recent_results || [];
  const form = data?.form || [];
  const summary = data?.season_summary;
  const hasMatches = upcoming.length > 0 || results.length > 0;
  // A team with a squad but no matches yet opens straight on the squad.
  const activeTab = tab === "matches" && !hasMatches && squad.length > 0 ? "squad" : tab;

  return (
    <div className="section tp">
      <button className="back-btn" onClick={onBack}>← Back</button>

      {loading ? (
        <LoadingState message="Loading team profile..." />
      ) : data?.error ? (
        <ErrorState title="Could not load team" message={data.error} />
      ) : (
        <>
          <header className="tp-hero">
            <div className="tp-hero-top">
              <TeamLogo src={data.logo_url} name={data.team_name} className="team-profile-badge-img tp-badge" />
              <div className="tp-hero-text">
                <h2 className="tp-name">{data.team_name || "Unknown Team"}</h2>
                {data.position && <span className="tp-pos">#{data.position} in league</span>}
              </div>
              {toggleFavorite && (
                <button
                  type="button"
                  className={`tp-fav ${isFavorite?.(teamUrl) ? "active" : ""}`}
                  onClick={() => toggleFavorite(teamUrl, data.team_name)}
                  aria-label={isFavorite?.(teamUrl) ? "Remove from Your Teams" : "Add to Your Teams"}
                  title={isFavorite?.(teamUrl) ? "Remove from Your Teams" : "Add to Your Teams"}
                >
                  {isFavorite?.(teamUrl) ? "★" : "☆"}
                </button>
              )}
            </div>

            {(summary || form.length > 0) && (
              <div className="tp-hero-stats">
                {summary && (
                  <dl className="tp-stats">
                    <div><dd>{summary.won}</dd><dt>W</dt></div>
                    <div><dd>{summary.drawn}</dd><dt>D</dt></div>
                    <div><dd>{summary.lost}</dd><dt>L</dt></div>
                    <div><dd>{summary.goals_for}</dd><dt>GF</dt></div>
                    <div><dd>{summary.goals_against}</dd><dt>GA</dt></div>
                  </dl>
                )}
                {form.length > 0 && (
                  <div className="tp-form">
                    <span className="tp-form-label">Form</span>
                    <div className="form-dots">
                      {form.map((f, i) => (
                        <div key={i} className={`form-dot tp-form-dot form-${f === "?" ? "unknown" : f}`}>{f}</div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </header>

          <div className="tp-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={activeTab === "matches"}
              className={activeTab === "matches" ? "active" : ""}
              onClick={() => setTab("matches")}
            >
              Matches
            </button>
            <button
              role="tab"
              aria-selected={activeTab === "squad"}
              className={activeTab === "squad" ? "active" : ""}
              onClick={() => setTab("squad")}
            >
              Squad{squad.length > 0 ? ` (${squad.length})` : ""}
            </button>
          </div>

          {activeTab === "matches" && (
            <div className="tp-panel">
              {!hasMatches && (
                <ErrorState
                  title="No match history found"
                  message="No fixtures or results are available for this team yet — check back once the season is further underway."
                  compact
                />
              )}

              {upcoming.length > 0 && (
                <section className="tp-group">
                  <h3 className="tp-group-title">Upcoming</h3>
                  <div className="tp-list">
                    {upcoming.map((f, i) => {
                      const { day, time } = splitDateTime(f.date);
                      return (
                        <div key={i} className="tp-match">
                          <div className="tp-when">
                            <b>{day}</b>
                            {time && <span>{time}</span>}
                          </div>
                          <div className="tp-opp">
                            <span className="tp-opp-name">vs {f.opponent}</span>
                            {f.venue && <span className="tp-opp-sub">{f.venue}</span>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}

              {results.length > 0 ? (
                <section className="tp-group">
                  <h3 className="tp-group-title">Results ({results.length})</h3>
                  <div className="tp-list">
                    {results.map((r, i) => (
                      <div key={i} className="tp-match">
                        {r.outcome ? (
                          <div className={`form-dot tp-outcome form-${r.outcome}`}>{r.outcome}</div>
                        ) : (
                          <div className="tp-outcome tp-outcome-none" />
                        )}
                        <div className="tp-opp">
                          <span className="tp-opp-name">vs {r.opponent}</span>
                          <span className="tp-opp-sub">{[r.date, r.venue].filter(Boolean).join(" · ")}</span>
                        </div>
                        <div className="tp-score">{r.result}</div>
                      </div>
                    ))}
                  </div>
                  {summary && summary.played_per_table > summary.matches_listed && (
                    <p className="tp-note">
                      The league table shows {summary.played_per_table} games played; {summary.matches_listed} match
                      {summary.matches_listed === 1 ? "" : "es"} listed so far. The rest appear once published.
                    </p>
                  )}
                </section>
              ) : (
                hasMatches && (
                  <section className="tp-group">
                    <h3 className="tp-group-title">Results</h3>
                    <p className="tp-note">No completed matches recorded for {data.team_name || "this team"} yet this season.</p>
                  </section>
                )
              )}
            </div>
          )}

          {activeTab === "squad" && (
            <div className="tp-panel">
              {squad.length === 0 ? (
                <p className="tp-note">No squad has been published for this team yet.</p>
              ) : (
                <div className="tp-squad">
                  {squad.map((p) => (
                    <button
                      key={p.player_id}
                      className="tp-player"
                      onClick={() => onOpenPlayer && onOpenPlayer(p.player_id)}
                      disabled={!onOpenPlayer}
                    >
                      <PlayerAvatar id={p.player_id} name={p.player_name} hasPhoto={p.has_photo} size={52} />
                      <span className="tp-player-name">
                        {p.player_name}
                        {p.captain && <span className="pl-captain" title="Captain">C</span>}
                      </span>
                      <span className="tp-player-sub">
                        {[p.jersey != null ? `#${p.jersey}` : "", p.position].filter(Boolean).join(" · ") || "Player"}
                      </span>
                      {p.goals > 0 && <span className="tp-player-goals">{p.goals} {p.goals === 1 ? "goal" : "goals"}</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
