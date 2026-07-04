import { useRef, useEffect, useState } from "react";

/**
 * useDiffedStandings — compares the previous standings snapshot to the new one
 * and tags each team row with what changed, so the UI can animate it.
 *
 * Mirrors how FotMob/SofaScore briefly highlight a row when its points or
 * position changes on a live poll, instead of silently re-rendering the
 * whole table every 45s.
 *
 * Returns an array of rows, each augmented with:
 *   _rankDelta   : +N = moved up N places, -N = moved down N places, 0 = no change
 *   _pointsDelta : how many points were gained since the last update
 *   _flash       : true for ~2.2s right after any change, then auto-clears
 */
export function useDiffedStandings(standings) {
  // team name -> { position:number, points:number }
  const prevRef = useRef(new Map());
  // team name -> { rankDelta, pointsDelta, expiresAt }
  const [changes, setChanges] = useState({});

  useEffect(() => {
    if (!standings || standings.length === 0) return;

    const prev = prevRef.current;
    const newChanges = {};

    standings.forEach(team => {
      const prior = prev.get(team.team);
      if (prior) {
        const prevPos = parseInt(prior.position, 10);
        const newPos = parseInt(team.position, 10);
        const prevPts = parseInt(prior.points, 10);
        const newPts = parseInt(team.points, 10);

        const rankDelta = (!isNaN(prevPos) && !isNaN(newPos)) ? (prevPos - newPos) : 0;
        const pointsDelta = (!isNaN(prevPts) && !isNaN(newPts)) ? (newPts - prevPts) : 0;

        if (rankDelta !== 0 || pointsDelta !== 0) {
          newChanges[team.team] = { rankDelta, pointsDelta };
        }
      }
    });

    if (Object.keys(newChanges).length > 0) {
      setChanges(c => ({ ...c, ...newChanges }));
      Object.keys(newChanges).forEach(teamName => {
        setTimeout(() => {
          setChanges(c => {
            const copy = { ...c };
            delete copy[teamName];
            return copy;
          });
        }, 2200);
      });
    }

    // Snapshot current state for the *next* comparison
    const nextSnapshot = new Map();
    standings.forEach(team => {
      nextSnapshot.set(team.team, { position: team.position, points: team.points });
    });
    prevRef.current = nextSnapshot;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standings]);

  if (!standings) return [];

  return standings.map(team => {
    const change = changes[team.team];
    return {
      ...team,
      _flash: Boolean(change),
      _rankDelta: change ? change.rankDelta : 0,
      _pointsDelta: change ? change.pointsDelta : 0,
    };
  });
}
