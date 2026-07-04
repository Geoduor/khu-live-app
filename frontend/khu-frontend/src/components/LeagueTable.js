import React from "react";
import { useDiffedStandings } from "../hooks/useDiffedStandings";

export default function LeagueTable({ data, onOpenTeam }) {
  const rows = useDiffedStandings(data);

  return (
    <table className="league-table">
      <thead>
        <tr>
          <th style={{ width: "100%" }}>Team</th>
          <th>Pl</th><th>W</th><th>D</th><th>L</th>
          <th style={{ color: "var(--amber)" }}>Pts</th>
          <th>GD</th>
          <th>Form</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t, i) => {
          const gd = parseInt(t.goal_diff, 10);
          const gdClass = isNaN(gd) ? "gd-zero" : gd > 0 ? "gd-pos" : gd < 0 ? "gd-neg" : "gd-zero";
          const gdDisplay = isNaN(gd) ? t.goal_diff : (gd > 0 ? `+${gd}` : `${gd}`);
          const clickable = Boolean(t.team_url && onOpenTeam);

          return (
            <tr key={t.team + i} className={t._flash ? "row-flash" : ""}>
              <td>
                <div
                  className={`team-cell ${clickable ? "team-cell-clickable" : ""}`}
                  onClick={() => clickable && onOpenTeam(t.team_url)}
                >
                  <span className="pos-num">
                    {t.position}
                    {t._rankDelta > 0 && <span className="rank-arrow rank-up">▲</span>}
                    {t._rankDelta < 0 && <span className="rank-arrow rank-down">▼</span>}
                  </span>
                  <div className="team-color-bar" />
                  <span className="team-tname">{t.team}</span>
                </div>
              </td>
              <td style={{ color: "var(--muted)" }}>{t.played}</td>
              <td style={{ fontWeight: 700 }}>{t.won}</td>
              <td style={{ color: "var(--muted)" }}>{t.drawn}</td>
              <td style={{ color: "var(--muted)" }}>{t.lost}</td>
              <td className="pts-td">
                {t.points}
                {t._pointsDelta > 0 && <span className="pts-gain">+{t._pointsDelta}</span>}
              </td>
              <td className={`gd-td ${gdClass}`}>{gdDisplay}</td>
              <td>
                <div className="form-dots">
                  {t.form && t.form.length > 0 ? (
                    t.form.map((f, fi) => (
                      <div key={fi} className={`form-dot form-${f}`}>{f}</div>
                    ))
                  ) : (
                    <span className="form-dash">—</span>
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
