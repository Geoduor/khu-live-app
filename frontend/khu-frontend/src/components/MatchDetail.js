import React, { useState, useEffect } from "react";
import { getMatchDetail } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";

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

          <div className="match-detail-body">
            <div
              className="match-detail-team"
              onClick={() => data.home_team_url && onOpenTeam(data.home_team_url)}
            >
              {data.home_team || "TBD"}
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
              onClick={() => data.away_team_url && onOpenTeam(data.away_team_url)}
            >
              {data.away_team || "TBD"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
