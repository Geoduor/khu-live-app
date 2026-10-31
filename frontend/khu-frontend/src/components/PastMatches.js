import React, { useEffect, useState, useCallback } from "react";
import MatchCard from "./MatchCard";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";
import { getMatchHistory } from "../api";

const PAGE = 30;

/** Permanent archive: every fixture and result we have ever recorded. */
export default function PastMatches({ leagues, onOpenMatch, onOpenTeam, isFavorite, toggleFavorite }) {
  const [league, setLeague] = useState("");
  const [season, setSeason] = useState("");
  const [team, setTeam] = useState("");
  const [teamInput, setTeamInput] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [seasons, setSeasons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (offset) => {
    setLoading(true);
    setError("");
    try {
      const d = await getMatchHistory({
        league, season, team, date_from: from, date_to: to, limit: PAGE, offset,
      });
      setRows((prev) => (offset ? [...prev, ...d.matches] : d.matches));
      setTotal(d.total);
      setSeasons(d.seasons || []);
    } catch (e) {
      setError("Could not load past matches. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [league, season, team, from, to]);

  useEffect(() => { load(0); }, [load]);

  // wait for the user to stop typing before searching by team
  useEffect(() => {
    const t = setTimeout(() => setTeam(teamInput.trim()), 400);
    return () => clearTimeout(t);
  }, [teamInput]);

  return (
    <div>
      <div className="archive-filters">
        <select aria-label="League" value={league} onChange={(e) => setLeague(e.target.value)}>
          <option value="">All leagues</option>
          {(leagues || []).map((l) => <option key={l.short} value={l.short}>{l.name}</option>)}
        </select>
        <select aria-label="Season" value={season} onChange={(e) => setSeason(e.target.value)}>
          <option value="">All seasons</option>
          {seasons.map((s) => <option key={s.season} value={s.season}>{s.season}</option>)}
        </select>
        <input className="wide" aria-label="Team" placeholder="Search a team, e.g. Strathmore" value={teamInput}
               maxLength={60} onChange={(e) => setTeamInput(e.target.value)} />
        <input aria-label="From date" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <input aria-label="To date" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>

      {error ? (
        <ErrorState title="Something went wrong" message={error} compact />
      ) : loading && rows.length === 0 ? (
        <LoadingState message="Loading past matches..." />
      ) : rows.length === 0 ? (
        <ErrorState title="No matches found" message="Nothing in the records matches these filters yet." compact />
      ) : (
        <>
          <div className="archive-count">{total} match{total === 1 ? "" : "es"} on record</div>
          {rows.map((m) => (
            <MatchCard key={m.match_key} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam}
                       isFavorite={isFavorite} toggleFavorite={toggleFavorite} />
          ))}
          {rows.length < total && (
            <button className="archive-more" disabled={loading} onClick={() => load(rows.length)}>
              {loading ? "Loading..." : "Show more"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
