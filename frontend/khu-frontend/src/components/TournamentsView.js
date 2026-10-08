import React, { useState, useEffect, useCallback } from "react";
import { getTournaments, getTournament } from "../api";
import MatchCard from "./MatchCard";
import ShareButton from "./ShareButton";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";
import { renderTableCard, shareCanvas, slug, shareText } from "../utils/shareCard";

const STATUS_LABEL = { upcoming: "Upcoming", ongoing: "Happening now", completed: "Completed" };

function dateRange(t) {
  if (t.start_date && t.end_date && t.start_date !== t.end_date) return `${t.start_date} → ${t.end_date}`;
  return t.start_date || t.end_date || "";
}

/**
 * TournamentsView — hosted tournaments, kept completely separate from
 * the league tables/fixtures/results. List → tap a tournament → its
 * matches (grouped by stage, Final first) and computed group tables.
 */
export default function TournamentsView() {
  const [list, setList] = useState(null);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState(null);

  const load = useCallback(() => {
    setError("");
    getTournaments()
      .then((d) => setList(d.tournaments || []))
      .catch(() => setError("Could not load tournaments. Check your connection and try again."));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (selectedId) {
    return <TournamentDetail id={selectedId} onBack={() => setSelectedId(null)} />;
  }

  return (
    <div className="section">
      <div className="sec-head">
        <span className="sec-title">Tournaments</span>
      </div>
      <div className="tour-note">Hosted tournaments and festivals — separate from league standings.</div>
      {error ? (
        <ErrorState title="Could not load tournaments" message={error} />
      ) : list === null ? (
        <LoadingState message="Loading tournaments..." />
      ) : list.length === 0 ? (
        <ErrorState
          title="No tournaments yet"
          message="When a tournament is added, its fixtures, results and group tables will show up here."
          compact
        />
      ) : (
        <div className="match-list">
          {list.map((t) => (
            <div key={t.id} className="tour-card" onClick={() => setSelectedId(t.id)}>
              <div className="tour-card-top">
                <span className={`tour-status tour-status-${t.status}`}>{STATUS_LABEL[t.status] || t.status}</span>
                <span className="tour-dates">{dateRange(t)}</span>
              </div>
              <div className="tour-name">{t.name}</div>
              {t.venue && <div className="tour-venue">📍 {t.venue}</div>}
              <div className="tour-count">{t.matches_played} of {t.matches_total} matches played</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TournamentDetail({ id, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("matches");

  useEffect(() => {
    setData(null); setError("");
    getTournament(id)
      .then(setData)
      .catch(() => setError("Could not load this tournament."));
  }, [id]);

  const t = data?.tournament;
  const hasTables = (data?.group_tables || []).length > 0;

  const shareGroup = async (g) => {
    const canvas = await renderTableCard({
      title: `${t.name} — ${g.group}`,
      subtitle: "Group table",
      rows: g.rows.map((r) => ({ ...r, logo: "" })),
    }, "Results entered by KHU Live");
    return shareCanvas(canvas, `${slug(t.name)}-${slug(g.group)}.png`, shareText(`${t.name} — ${g.group}`));
  };

  return (
    <div className="section">
      <button className="back-btn" onClick={onBack}>← Back</button>
      {error ? (
        <ErrorState title="Something went wrong" message={error} />
      ) : !data ? (
        <LoadingState message="Loading tournament..." />
      ) : (
        <>
          <div className="tour-hero">
            <span className={`tour-status tour-status-${t.status}`}>{STATUS_LABEL[t.status] || t.status}</span>
            <div className="tour-hero-name">{t.name}</div>
            <div className="tour-dates">{dateRange(t)}{t.venue ? ` · ${t.venue}` : ""}</div>
            {t.description && <div className="tour-desc">{t.description}</div>}
          </div>

          <div className="tour-tabs">
            <button className={tab === "matches" ? "on" : ""} onClick={() => setTab("matches")}>Matches ({data.totals.matches})</button>
            {hasTables && <button className={tab === "tables" ? "on" : ""} onClick={() => setTab("tables")}>Group tables</button>}
          </div>

          {tab === "matches" && (
            data.matches.length === 0 ? (
              <ErrorState title="No matches yet" message="Fixtures and results will appear here once they are added." compact />
            ) : (
              data.stages.map((stage) => (
                <div key={stage} className="tour-stage">
                  <div className="date-group-header">{stage}</div>
                  <div className="match-list">
                    {data.matches.filter((m) => m.stage === stage).map((m) => (
                      <MatchCard
                        key={m.match_id}
                        match={{ ...m, league: t.name, matchday: "", share_source: "Results entered by KHU Live" }}
                      />
                    ))}
                  </div>
                </div>
              ))
            )
          )}

          {tab === "tables" && data.group_tables.map((g) => (
            <div key={g.group} className="tour-stage">
              <div className="tour-table-head">
                <div className="date-group-header" style={{ margin: 0 }}>{g.group}</div>
                <ShareButton label="Share table" onShare={() => shareGroup(g)} />
              </div>
              <div className="table-scroll">
                <table className="league-table">
                  <thead>
                    <tr>
                      <th style={{ width: "100%" }}>Team</th>
                      <th>Pl</th><th>W</th><th>D</th><th>L</th><th>GD</th>
                      <th style={{ color: "var(--amber)" }}>Pts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.rows.map((r) => (
                      <tr key={r.team}>
                        <td><div className="team-cell"><span className="pos-num">{r.position}</span><span className="team-tname">{r.team}</span></div></td>
                        <td style={{ color: "var(--muted)" }}>{r.played}</td>
                        <td style={{ fontWeight: 700 }}>{r.won}</td>
                        <td style={{ color: "var(--muted)" }}>{r.drawn}</td>
                        <td style={{ color: "var(--muted)" }}>{r.lost}</td>
                        <td className={`gd-td ${r.goal_diff > 0 ? "gd-pos" : r.goal_diff < 0 ? "gd-neg" : "gd-zero"}`}>{r.goal_diff > 0 ? `+${r.goal_diff}` : r.goal_diff}</td>
                        <td className="pts-td">{r.points}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
