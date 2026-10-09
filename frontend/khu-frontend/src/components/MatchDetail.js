import React, { useState, useEffect } from "react";
import { getMatchDetail } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";
import TeamLogo from "./TeamLogo";
import ShareButton from "./ShareButton";
import { teamLogoUrl } from "../api";
import { renderMatchCard, shareCanvas, slug, shareText } from "../utils/shareCard";

const CARD_ICON = { green: "🟩", yellow: "🟨", red: "🟥" };

/** Goals and cards merged into one list ordered by minute (no-minute last). */
function buildEvents(scorers, cards) {
  const ev = [
    ...(scorers || []).map((s) => ({ kind: "goal", team: s.team, player: s.player_name, minute: s.minute })),
    ...(cards || []).map((c) => ({ kind: c.card_type || "yellow", team: c.team, player: c.player_name, minute: c.minute })),
  ];
  return ev
    .map((e, i) => ({ ...e, i }))
    .sort((a, b) => (a.minute ?? 999) - (b.minute ?? 999) || a.i - b.i);
}

function EventRow({ e }) {
  const label = (
    <span className="md-ev-text">
      <span className="md-ev-icon">{e.kind === "goal" ? "⚽" : CARD_ICON[e.kind] || "🟨"}</span>
      {e.player}
      {e.minute != null && <span className="md-ev-min"> {e.minute}'</span>}
    </span>
  );
  return (
    <div className="md-ev-row">
      <div className="md-ev-side md-ev-home">{e.team === "home" ? label : null}</div>
      <div className="md-ev-side md-ev-away">{e.team === "away" ? label : null}</div>
    </div>
  );
}

export default function MatchDetail({ matchUrl, onBack, onOpenTeam }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    getMatchDetail(matchUrl)
      .then(setData)
      .catch(() => setData({ error: "Could not load match detail" }))
      .finally(() => setLoading(false));
  }, [matchUrl]);

  return (
    <div className="section">
      <button className="back-btn" onClick={onBack}>← Back</button>

      {loading ? (
        <LoadingState message="Loading match detail..." />
      ) : data?.error ? (
        <ErrorState title="Could not load match" message={data.error} />
      ) : (
        <div className="match-detail-card">
          <div className="match-detail-meta">
            {data.matchday && <div className="match-detail-matchday">{data.matchday}</div>}
            {data.date && <div className="match-detail-date">📅 {data.date}</div>}
            {data.venue && <div className="match-detail-venue">📍 {data.venue}</div>}
          </div>

          {data.is_live && (
            <div className="match-state-live" style={{ justifyContent: "center", marginBottom: 12 }}>
              <span className="pulse-dot" /> LIVE NOW
            </div>
          )}

          {data.league && <div className="match-detail-matchday">{data.league}</div>}

          <div className="match-detail-body">
            <div
              className="match-detail-team"
              onClick={() => data.home_team_url && onOpenTeam(data.home_team_url, data.home_team)}
            >
              <TeamLogo src={data.home_logo_url} name={data.home_team} className="md-logo" />
              <div>{data.home_team || "TBD"}</div>
            </div>
            <div className="match-detail-score">
              {data.home_score != null ? (
                <>{data.home_score} <span style={{ color: "var(--muted)" }}>–</span> {data.away_score}</>
              ) : (
                <span className="score-tbd">VS</span>
              )}
            </div>
            <div
              className="match-detail-team"
              onClick={() => data.away_team_url && onOpenTeam(data.away_team_url, data.away_team)}
            >
              <TeamLogo src={data.away_logo_url} name={data.away_team} className="md-logo" />
              <div>{data.away_team || "TBD"}</div>
            </div>
          </div>

          {buildEvents(data.scorers, data.cards).length > 0 && (
            <div className="md-events">
              <div className="md-events-title">Match events</div>
              {buildEvents(data.scorers, data.cards).map((e) => <EventRow key={e.i} e={e} />)}
            </div>
          )}

          {data.home_score != null && data.away_score != null && (
            <div className="match-share-row" style={{ marginTop: 14 }}>
              <ShareButton
                label="Share result"
                onShare={async () => {
                  const canvas = await renderMatchCard({
                    ...data,
                    state: data.is_live ? "LIVE" : data.state || "FT",
                    home_logo: teamLogoUrl(data.home_logo_url),
                    away_logo: teamLogoUrl(data.away_logo_url),
                  });
                  return shareCanvas(
                    canvas,
                    `${slug(data.home_team)}-vs-${slug(data.away_team)}.png`,
                    shareText(`${data.home_team} ${data.home_score}-${data.away_score} ${data.away_team}${data.league ? " · " + data.league : ""}`)
                  );
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
