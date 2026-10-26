import React, { useState, useEffect, useCallback, useMemo } from "react";
import { getTournaments, getTournament } from "../api";
import ShareButton from "./ShareButton";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";
import { renderTableCard, shareCanvas, slug, shareText } from "../utils/shareCard";

const STATUS_LABEL = { upcoming: "Upcoming", ongoing: "Happening now", completed: "Completed" };

function fmt(s, withYear) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
  if (!m) return s || "";
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}) });
}
function dateRange(t) {
  if (t.start_date && t.end_date && t.start_date !== t.end_date) {
    const a = new Date(t.start_date), b = new Date(t.end_date);
    const sameMonth = a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear();
    return sameMonth ? `${a.getDate()} – ${fmt(t.end_date, true)}` : `${fmt(t.start_date)} – ${fmt(t.end_date, true)}`;
  }
  return fmt(t.start_date || t.end_date, true);
}
// The stored status is set by hand; show what the scores say.
function liveStatus(status, played, total) {
  if (total > 0 && played >= total) return "completed";
  if (played > 0) return "ongoing";
  return status;
}

/**
 * TournamentsView — hosted tournaments, kept completely separate from
 * the league tables/fixtures/results. List → tap a tournament → its
 * matches (grouped by stage, first game to last) and computed group tables.
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
                <span className={`tour-status tour-status-${liveStatus(t.status, t.matches_played, t.matches_total)}`}>{STATUS_LABEL[liveStatus(t.status, t.matches_played, t.matches_total)] || t.status}</span>
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

const SEP = " – ";
const catOf = (stage) => (stage.includes(SEP) ? stage.split(SEP)[0] : "");
const stageName = (stage) => (stage.includes(SEP) ? stage.split(SEP).slice(1).join(SEP) : stage);
const hasScore = (m) => m.home_score != null && m.away_score != null;

function parseDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?/.exec(s || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0)) : null;
}
const dayKey = (s) => (s || "").slice(0, 10);
const dayLabel = (s) => {
  const d = parseDate(s);
  return d ? d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" }) : "Date to be confirmed";
};
const timeLabel = (s) => ((s || "").length >= 16 ? s.slice(11, 16) : "");

function winnerOf(m) {
  if (!hasScore(m) || m.home_score === m.away_score) return "";
  return m.home_score > m.away_score ? m.home_team : m.away_team;
}

function ResultRow({ m }) {
  const done = hasScore(m);
  const w = winnerOf(m);
  return (
    <div className={`tr-row ${done ? "" : "tr-row-up"}`}>
      <div className="tr-time">{timeLabel(m.date) || "—"}</div>
      <div className={`tr-team tr-home ${w === m.home_team ? "tr-win" : done && w ? "tr-lose" : ""}`}>{m.home_team}</div>
      <div className={`tr-score ${done ? "" : "tr-vs"}`}>
        {done ? (<><span>{m.home_score}</span><i>–</i><span>{m.away_score}</span></>) : "vs"}
      </div>
      <div className={`tr-team tr-away ${w === m.away_team ? "tr-win" : done && w ? "tr-lose" : ""}`}>{m.away_team}</div>
    </div>
  );
}

function TournamentDetail({ id, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("results");
  const [cat, setCat] = useState("");

  useEffect(() => {
    setData(null); setError("");
    let alive = true;
    getTournament(id)
      .then((d) => alive && setData(d))
      .catch(() => alive && setError("Could not load this tournament."));
    return () => { alive = false; };
  }, [id]);

  const t = data?.tournament;
  const matches = useMemo(() => data?.matches || [], [data]);
  const cats = useMemo(() => {
    const seen = [];
    matches.forEach((m) => { const c = catOf(m.stage); if (c && !seen.includes(c)) seen.push(c); });
    return seen.sort((a, b) => (a === "Men" ? -1 : b === "Men" ? 1 : a.localeCompare(b)));
  }, [matches]);
  const active = cats.includes(cat) ? cat : cats[0] || "";

  const mine = useMemo(() => matches.filter((m) => !active || catOf(m.stage) === active), [matches, active]);
  const upNext = useMemo(
    () => mine.filter((m) => !hasScore(m)).sort((a, b) => (a.date || "").localeCompare(b.date || "")),
    [mine]
  );
  // Played games grouped by stage, latest stage first; inside a stage, latest game first.
  const stageGroups = useMemo(() => {
    const order = (data?.stages || []).filter((s) => !active || catOf(s) === active).slice().reverse();
    return order.map((s) => ({
      stage: s,
      games: mine.filter((m) => m.stage === s && hasScore(m)).sort((a, b) => (b.date || "").localeCompare(a.date || "")),
    })).filter((g) => g.games.length > 0);
  }, [data, mine, active]);

  const champions = useMemo(() => {
    const out = [];
    (cats.length ? cats : [""]).forEach((c) => {
      const f = matches.find((m) => (!c || catOf(m.stage) === c) && /^final$/i.test(stageName(m.stage)) && hasScore(m));
      const w = f && winnerOf(f);
      if (w) out.push({ cat: c, team: w });
    });
    return out;
  }, [matches, cats]);

  const groupsFor = (data?.group_tables || []).filter((g) => !active || g.group.startsWith(active));
  const played = data?.totals?.played ?? matches.filter(hasScore).length;
  const total = data?.totals?.matches ?? matches.length;
  const pct = total ? Math.round((played / total) * 100) : 0;

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
          <div className="tv-hero">
            <span className={`tour-status tour-status-${liveStatus(t.status, played, total)}`}>{STATUS_LABEL[liveStatus(t.status, played, total)] || t.status}</span>
            <div className="tv-name">{t.name}</div>
            <div className="tv-meta">{dateRange(t)}</div>
            {t.venue && <div className="tv-meta">📍 {t.venue}</div>}
            <div className="tv-progress" aria-label={`${played} of ${total} matches played`}>
              <div className="tv-bar"><span style={{ width: `${pct}%` }} /></div>
              <div className="tv-prog-txt">{played} of {total} matches played</div>
            </div>
          </div>

          {champions.length > 0 && (
            <div className="tv-champs">
              {champions.map((c) => (
                <div key={c.cat} className="tv-champ">
                  <div className="tv-trophy">🏆</div>
                  <div>
                    <div className="tv-champ-k">{c.cat ? `${c.cat} champions` : "Champions"}</div>
                    <div className="tv-champ-n">{c.team}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {cats.length > 1 && (
            <div className="tv-seg" role="tablist" aria-label="Competition">
              {cats.map((c) => (
                <button key={c} role="tab" aria-selected={active === c} className={active === c ? "on" : ""} onClick={() => setCat(c)}>{c}</button>
              ))}
            </div>
          )}

          <div className="tv-tabs" role="tablist">
            <button role="tab" aria-selected={tab === "results"} className={tab === "results" ? "on" : ""} onClick={() => setTab("results")}>Results</button>
            {groupsFor.length > 0 && (
              <button role="tab" aria-selected={tab === "tables"} className={tab === "tables" ? "on" : ""} onClick={() => setTab("tables")}>Tables</button>
            )}
          </div>

          {tab === "results" && (
            matches.length === 0 ? (
              <ErrorState title="No matches yet" message="Fixtures and results will appear here once they are added." compact />
            ) : (
              <>
                {upNext.length > 0 && (
                  <div className="tv-block">
                    <div className="tv-block-h">Up next</div>
                    <div className="tv-card">
                      {upNext.map((m) => (
                        <div key={m.match_id}>
                          <div className="tv-stage-tag">{stageName(m.stage)} · {dayLabel(m.date)}</div>
                          <ResultRow m={m} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {stageGroups.length === 0 && upNext.length === 0 && (
                  <ErrorState title="No results yet" message="Scores will appear here as games finish." compact />
                )}
                {stageGroups.map((g) => {
                  const days = [];
                  g.games.forEach((m) => { const k = dayKey(m.date); if (!days.length || days[days.length - 1].k !== k) days.push({ k, d: m.date, games: [] }); days[days.length - 1].games.push(m); });
                  return (
                    <div key={g.stage} className="tv-block">
                      <div className="tv-block-h">{stageName(g.stage)}<span>{g.games.length} {g.games.length === 1 ? "game" : "games"}</span></div>
                      <div className="tv-card">
                        {days.map((d) => (
                          <div key={d.k}>
                            {(days.length > 1 || stageName(g.stage) === "Pool") && <div className="tv-day">{dayLabel(d.d)}</div>}
                            {d.games.map((m) => <ResultRow key={m.match_id} m={m} />)}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </>
            )
          )}

          {tab === "tables" && groupsFor.map((g) => (
            <div key={g.group} className="tv-block">
              <div className="tv-block-h">
                {g.group}
                <ShareButton label="Share table" onShare={() => shareGroup(g)} />
              </div>
              <div className="tv-card table-scroll">
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
                      <tr key={r.team} className={r.position <= 3 ? `tv-top tv-top-${r.position}` : ""}>
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
