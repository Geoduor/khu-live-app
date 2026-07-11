import React, { useState, useEffect } from "react";
import { getAllTeamsFlat } from "../api";

/**
 * OnboardingPicker — "Which teams do you follow?" first-run prompt.
 *
 * Finding 2 from research: passive star icons buried in team pages
 * massively under-deliver vs. an explicit prompt on first launch.
 * FotMob, TheScore, and ESPN all show this exact pattern before
 * letting the user into the main app.
 */
export default function OnboardingPicker({ onComplete }) {
  const [teams, setTeams] = useState([]);
  const [selected, setSelected] = useState([]); // array of team_url
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    getAllTeamsFlat()
      .then((data) => setTeams(data.teams || []))
      .catch(() => setTeams([]))
      .finally(() => setLoading(false));
  }, []);

  const toggle = (team) => {
    const key = team.team_url || team.name;
    setSelected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  };

  const filtered = teams.filter((t) => t.name.toLowerCase().includes(search.toLowerCase()));

  const handleContinue = () => {
    // Pass full {team_url, team_name} pairs up, not just keys, so the
    // parent can seed useFavorites with proper display names too.
    const chosen = teams
      .filter((t) => selected.includes(t.team_url || t.name))
      .map((t) => ({ team_url: t.team_url || t.name, team_name: t.name }));
    onComplete(chosen);
  };

  return (
    <div className="onboarding-overlay">
      <div className="onboarding-card">
        <div className="onboarding-header">
          <img src="/khu-logo.png" alt="KHU" className="onboarding-logo-img" />
          <div className="onboarding-title">Which teams do you follow?</div>
          <div className="onboarding-sub">
            Pick your favorites — we'll show their matches first and can alert you only about them.
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: "30px 0", color: "var(--muted)" }}>Loading teams...</div>
        ) : (
          <>
            <input
              className="onboarding-search"
              placeholder="Search teams..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="onboarding-team-list">
              {filtered.map((t) => {
                const key = t.team_url || t.name;
                return (
                  <div
                    key={key}
                    className={`onboarding-team-row ${selected.includes(key) ? "selected" : ""}`}
                    onClick={() => toggle(t)}
                  >
                    <div>
                      <div className="onboarding-team-name">{t.name}</div>
                      <div className="onboarding-team-league">{t.league}</div>
                    </div>
                    <div className="onboarding-checkbox">{selected.includes(key) ? "✓" : ""}</div>
                  </div>
                );
              })}
              {filtered.length === 0 && (
                <div style={{ textAlign: "center", padding: "20px", color: "var(--muted)", fontSize: 13 }}>
                  No teams match "{search}"
                </div>
              )}
            </div>
          </>
        )}

        <div className="onboarding-actions">
          <button className="onboarding-skip" onClick={() => onComplete([])}>
            Skip for now
          </button>
          <button
            className="onboarding-continue"
            onClick={handleContinue}
            disabled={selected.length === 0}
          >
            {selected.length > 0 ? `Follow ${selected.length} team${selected.length > 1 ? "s" : ""}` : "Select a team"}
          </button>
        </div>
      </div>
    </div>
  );
}
