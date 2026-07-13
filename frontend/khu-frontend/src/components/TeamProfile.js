import React, { useState, useEffect } from "react";
import { getTeamProfile } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";

export default function TeamProfile({ teamUrl, teamName, onBack, onOpenTeam, isFavorite, toggleFavorite }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    getTeamProfile(teamUrl, teamName)
      .then(setData)
      .catch(() => setData({ error: "Could not load team profile" }))
      .finally(() => setLoading(false));
  }, [teamUrl, teamName]);

  return (
    <div className="section">
      <button className="back-btn" onClick={onBack}>← Back</button>

      {loading ? (
        <LoadingState message="Loading team profile..." />
      ) : data?.error ? (
        <ErrorState title="Could not load team" message={data.error} />
      ) : (
        <>
          <div className="team-profile-header">
            {data.logo_url ? (
              <img src={data.logo_url} alt="" className="team-profile-badge-img" />
            ) : (
              <div className="team-profile-badge">
                {(data.team_name || "?").slice(0, 2).toUpperCase()}
              </div>
            )}
            <div style={{ flex: 1 }}>
              <div className="team-profile-name">{data.team_name || "Unknown Team"}</div>
              {data.position && (
                <div className="team-profile-position">League Position: #{data.position}</div>
              )}
            </div>
            {toggleFavorite && (
              <span
                className={`fav-star fav-star-lg ${isFavorite?.(teamUrl) ? "active" : ""}`}
                onClick={() => toggleFavorite(teamUrl, data.team_name)}
                title={isFavorite?.(teamUrl) ? "Remove from Your Teams" : "Add to Your Teams"}
              >
                {isFavorite?.(teamUrl) ? "★" : "☆"}
              </span>
            )}
          </div>

          {data.form && data.form.length > 0 && (
            <div className="profile-block">
              <div className="profile-block-title">Current Form</div>
              <div className="form-dots" style={{ justifyContent: "flex-start" }}>
                {data.form.map((f, i) => (
                  <div key={i} className={`form-dot form-${f === "?" ? "unknown" : f}`} style={{ width: 26, height: 26, fontSize: 12 }}>{f}</div>
                ))}
              </div>
            </div>
          )}

          {data.upcoming_fixtures && data.upcoming_fixtures.length > 0 && (
            <div className="profile-block">
              <div className="profile-block-title">Upcoming Fixtures</div>
              <div className="match-list">
                {data.upcoming_fixtures.map((f, i) => (
                  <div key={i} className="mini-match-row">
                    <div className="mini-match-date">{f.date}</div>
                    <div className="mini-match-opp">vs {f.opponent}</div>
                    <div className="mini-match-venue">{f.venue}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.recent_results && data.recent_results.length > 0 && (
            <div className="profile-block">
              <div className="profile-block-title">Recent Results</div>
              <div className="match-list">
                {data.recent_results.map((r, i) => (
                  <div key={i} className="mini-match-row">
                    <div className="mini-match-date">{r.date}</div>
                    <div className="mini-match-opp">vs {r.opponent}</div>
                    <div className="mini-match-result">{r.result}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(!data.upcoming_fixtures || data.upcoming_fixtures.length === 0) &&
           (!data.recent_results || data.recent_results.length === 0) && (
            <ErrorState
              title="No match history found"
              message="This team's profile page didn't have parseable fixture/result blocks yet."
              compact
            />
          )}
        </>
      )}
    </div>
  );
}
