import React from "react";

/**
 * MatchCard — renders a single match using JoomSport's real match state machine:
 *   NS   = not started (upcoming fixture)
 *   LIVE = in progress right now
 *   FT   = finished (final score)
 *
 * Tapping the card opens the match detail page (if a real match_url exists).
 * Tapping a team name opens that team's profile directly.
 * Star icons let users favorite either team directly from the match card.
 */
export default function MatchCard({ match, onOpenMatch, onOpenTeam, isFavorite, toggleFavorite }) {
  const state = match.state || (match.home_score != null ? "FT" : "NS");
  const clickable = Boolean(match.match_url && onOpenMatch);

  return (
    <div
      className={`match-card ${state === "LIVE" ? "match-card-live" : ""} ${clickable ? "match-card-clickable" : ""}`}
      onClick={() => clickable && onOpenMatch(match.match_url)}
    >
      <div className="match-meta">
        <div>
          {match.league && <div className="match-league">{match.league}</div>}
          {match.matchday && <div className="match-venue">{match.matchday}</div>}
          {match.date && <div className="match-venue">{match.date}</div>}
        </div>

        {state === "LIVE" && (
          <div className="match-state-live">
            <span className="pulse-dot" /> LIVE
          </div>
        )}
        {state === "FT" && <div className="match-state-ft">FULL TIME</div>}
        {state === "NS" && <div className="match-state-ns">UPCOMING</div>}
      </div>

      <div className="match-body">
        <div className="team-col" style={{ textAlign: "right" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6 }}>
            <div
              className={`team-name ${match.home_team_url ? "team-name-link" : ""}`}
              onClick={(e) => {
                if (match.home_team_url && onOpenTeam) {
                  e.stopPropagation();
                  onOpenTeam(match.home_team_url);
                }
              }}
            >
              {match.home_team || "TBD"}
            </div>
            {toggleFavorite && match.home_team_url && (
              <span
                className={`fav-star ${isFavorite?.(match.home_team_url) ? "active" : ""}`}
                onClick={(e) => { e.stopPropagation(); toggleFavorite(match.home_team_url, match.home_team); }}
              >
                {isFavorite?.(match.home_team_url) ? "★" : "☆"}
              </span>
            )}
          </div>
        </div>
        <div className="score-col">
          {(state === "FT" || state === "LIVE") && match.home_score != null ? (
            <div className="score-display">
              {match.home_score} <span style={{ color: "var(--muted)", fontWeight: 400 }}>–</span> {match.away_score}
            </div>
          ) : (
            <div className="score-tbd">VS</div>
          )}
        </div>
        <div className="team-col">
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {toggleFavorite && match.away_team_url && (
              <span
                className={`fav-star ${isFavorite?.(match.away_team_url) ? "active" : ""}`}
                onClick={(e) => { e.stopPropagation(); toggleFavorite(match.away_team_url, match.away_team); }}
              >
                {isFavorite?.(match.away_team_url) ? "★" : "☆"}
              </span>
            )}
            <div
              className={`team-name ${match.away_team_url ? "team-name-link" : ""}`}
              onClick={(e) => {
                if (match.away_team_url && onOpenTeam) {
                  e.stopPropagation();
                  onOpenTeam(match.away_team_url);
                }
              }}
            >
              {match.away_team || "TBD"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
