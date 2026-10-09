import React, { useEffect, useState } from "react";
import { getTopScorers } from "../api";
import LoadingState from "./LoadingState";
import ShareButton from "./ShareButton";
import { renderScorersCard, shareCanvas, slug, shareText } from "../utils/shareCard";

/**
 * Top scorers for one league. Goals come from season stat lines entered
 * by admin/agents plus goals recorded on individual results — so the
 * list is only as complete as the scorers KHU Live has been given.
 */
export default function TopScorers({ leagueShort, leagueName, onOpenTeam }) {
  const [players, setPlayers] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setPlayers(null);
    setFailed(false);
    getTopScorers(leagueShort)
      .then((d) => alive && setPlayers(d.players || []))
      .catch(() => alive && setFailed(true));
    return () => { alive = false; };
  }, [leagueShort]);

  if (failed) return <div className="empty-note">Could not load top scorers right now.</div>;
  if (!players) return <LoadingState message="Loading top scorers..." />;
  if (players.length === 0) {
    return (
      <div className="empty-note">
        No goal scorers recorded yet for {leagueName}. They appear here as results are entered with scorers.
      </div>
    );
  }

  const top = players.slice(0, 20);
  return (
    <div>
      <div className="ts-head">
        <span>{leagueName} — top scorers</span>
        <ShareButton
          label="Share"
          onShare={async () => {
            const canvas = await renderScorersCard({
              title: `${leagueName} top scorers`,
              subtitle: new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }),
              rows: top,
            }, "Based on goals recorded in KHU Live");
            return shareCanvas(canvas, `${slug(leagueName)}-top-scorers.png`, shareText(`${leagueName} — top scorers`));
          }}
        />
      </div>
      <div className="ts-list">
        {top.map((p, i) => (
          <div className="ts-row" key={`${p.player_name}|${p.team_name}|${i}`}>
            <span className={`ts-rank ${i === 0 ? "ts-rank-1" : ""}`}>{i + 1}</span>
            <div className="ts-who">
              <div className="ts-name">{p.player_name}</div>
              <div className="ts-team">{p.team_name}</div>
            </div>
            <div className="ts-goals">{p.goals}<span>goals</span></div>
          </div>
        ))}
      </div>
      <div className="ts-note">Based on goals recorded in KHU Live — may not include every goal.</div>
    </div>
  );
}
