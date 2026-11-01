import React, { useEffect, useState } from "react";
import { getPlayer, playerPhotoUrl, teamLogoUrl } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";
import TeamLogo from "./TeamLogo";

function initials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
}

/** Round photo, or the player's initials when no photo has been added. */
export function PlayerAvatar({ id, name, hasPhoto, size = 44, version }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [id, version]);
  const style = { width: size, height: size, fontSize: Math.round(size * 0.38) };
  if (hasPhoto && !failed) {
    return <img className="pl-avatar" style={style} src={playerPhotoUrl(id, version)} alt={name || "Player"} loading="lazy" onError={() => setFailed(true)} />;
  }
  return <div className="pl-avatar pl-avatar-fallback" style={style} aria-hidden="true">{initials(name)}</div>;
}

/** One player: photo, details, season stats and the goals they've scored. */
export default function PlayerProfile({ playerId, onBack, onOpenTeam }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(false);
    getPlayer(playerId)
      .then((d) => alive && setData(d))
      .catch(() => alive && setError(true));
    return () => { alive = false; };
  }, [playerId]);

  return (
    <div className="section">
      <button className="back-btn" onClick={onBack}>← Back</button>
      {error ? (
        <ErrorState title="Could not load this player" message="They may not be on record yet. Please try again." />
      ) : !data ? (
        <LoadingState message="Loading player..." />
      ) : (
        <>
          <div className="pl-hero">
            <PlayerAvatar id={data.player_id} name={data.player_name} hasPhoto={data.has_photo} size={96} />
            <div className="pl-hero-text">
              <div className="pl-name">
                {data.player_name}
                {data.captain && <span className="pl-captain" title="Captain">C</span>}
              </div>
              <div className="pl-sub">
                {[data.position, data.jersey != null ? `#${data.jersey}` : "", data.nationality].filter(Boolean).join(" · ") || "Player"}
              </div>
              <button
                className="pl-team"
                onClick={() => onOpenTeam && onOpenTeam(data.team_url, data.team_name, data.league_short)}
                disabled={!onOpenTeam}
              >
                <TeamLogo src={teamLogoUrl(data.team_logo_url)} name={data.team_name} className="team-logo-sm" />
                <span>{data.team_name}</span>
              </button>
              <div className="pl-league">{data.league}</div>
            </div>
          </div>

          {data.bio && <div className="profile-block"><div className="pl-bio">{data.bio}</div></div>}

          <div className="profile-block">
            <div className="profile-block-title">Season stats</div>
            <div className="pl-stats">
              <div><b>{data.goals}</b><span>Goals</span></div>
              {data.has_stat_line && <div><b>{data.appearances}</b><span>Apps</span></div>}
              {data.has_stat_line && <div><b>{data.green_cards}</b><span>Green</span></div>}
              {data.has_stat_line && <div><b>{data.yellow_cards}</b><span>Yellow</span></div>}
              {data.has_stat_line && <div><b>{data.red_cards}</b><span>Red</span></div>}
            </div>
            <div className="ts-note">Based on what has been recorded in KHU Live. It may not include every game.</div>
          </div>

          <div className="profile-block">
            <div className="profile-block-title">Goals this season ({data.goals_log.length})</div>
            {data.goals_log.length ? (
              <div className="match-list">
                {data.goals_log.map((g, i) => (
                  <div key={i} className="mini-match-row">
                    <div className="mini-match-date">{g.date}</div>
                    <div className="mini-match-opp">vs {g.opponent}</div>
                    <div className="mini-match-result">{g.minute != null ? `${g.minute}'` : ""}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="profile-block-empty">No individual goals recorded yet.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
