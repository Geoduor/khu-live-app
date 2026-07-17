import React, { useState, useEffect } from "react";
import { getPlayoffBracket } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";

/**
 * PlayoffBracket — visualizes the National League Men cross-zone
 * knockout structure (EZ/CZ meet in one half, WZ/SZ in the other,
 * converging at the semis and final).
 *
 * Honest data note: quarter-final seeding (which real teams occupy
 * each slot) comes from live NLM zone standings we already scrape —
 * so that part is genuinely real and up to date. Actual playoff
 * MATCH results aren't yet available from a confirmed scraped source
 * on KHU's site, so every round shows "vs" until we locate that data
 * once the playoffs begin — this is stated plainly in the UI rather
 * than faked.
 */
function BracketMatchup({ match, onOpenTeam }) {
  const isTBD = (team) => !team.team_url;

  return (
    <div className="bracket-match">
      <div className="bracket-match-meta">
        <span>{match.venue}</span>
        <span>{match.status}</span>
      </div>
      {[match.home, match.away].map((team, i) => (
        <div
          key={i}
          className={`bracket-team ${isTBD(team) ? "bracket-team-tbd" : "bracket-team-clickable"}`}
          onClick={() => !isTBD(team) && onOpenTeam(team.team_url, team.name)}
        >
          {team.logo_url && <img src={team.logo_url} alt="" className="team-logo-sm" />}
          <span className="bracket-team-name">{team.name}</span>
          {team.seed_label && <span className="bracket-seed-label">{team.seed_label}</span>}
        </div>
      ))}
    </div>
  );
}

export default function PlayoffBracket({ onBack, onOpenTeam }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPlayoffBracket()
      .then(setData)
      .catch(() => setData({ error: "Could not load playoff bracket" }))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="section">
      <button className="back-btn" onClick={onBack}>← Back</button>

      <div className="sec-head">
        <span className="sec-title">🏆 NLM Playoff Bracket</span>
      </div>

      {loading ? (
        <LoadingState message="Loading bracket..." />
      ) : data?.error ? (
        <ErrorState title="Could not load bracket" message={data.error} />
      ) : (
        <>
          <div className="source-notice">
            <strong>Seeding:</strong> live from current NLM zone standings.{" "}
            <strong>Match scores:</strong> not yet available — {data.match_results_note}
          </div>

          <div className="bracket-round">
            <div className="bracket-round-label">Quarter Finals</div>
            <div className="bracket-round-matches">
              {data.quarter_finals.map((m) => (
                <BracketMatchup key={m.id} match={m} onOpenTeam={onOpenTeam} />
              ))}
            </div>
          </div>

          <div className="bracket-round">
            <div className="bracket-round-label">Semi Finals</div>
            <div className="bracket-round-matches">
              {data.semi_finals.map((m) => (
                <BracketMatchup key={m.id} match={m} onOpenTeam={onOpenTeam} />
              ))}
            </div>
          </div>

          <div className="bracket-round bracket-round-final">
            <div className="bracket-round-label">3rd Place Play-Off</div>
            <div className="bracket-round-matches">
              <BracketMatchup match={data.third_place} onOpenTeam={onOpenTeam} />
            </div>
          </div>

          <div className="bracket-round bracket-round-final">
            <div className="bracket-round-label">🏆 Final</div>
            <div className="bracket-round-matches">
              <BracketMatchup match={data.final} onOpenTeam={onOpenTeam} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
