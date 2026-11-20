// Remembers the open tab (and the league on the Table tab) in the web address, e.g.
//   khulive.co.ke/#/results        khulive.co.ke/#/table/premier_league_men
// so a refresh, or a link sent to a friend, opens the same place instead of Home.
// Home keeps the clean address. Only known tab names and a plain league key are
// accepted, so a hand-edited or hostile address can never do anything else.
export const TAB_IDS = ["home", "table", "fixtures", "results", "tournaments"];
const LEAGUE_RE = /^[a-z0-9_-]{1,60}$/;

export function parseHash(hash) {
  const m = /^#\/([a-z]+)(?:\/([^/?#]*))?/.exec(String(hash || ""));
  if (!m || !TAB_IDS.includes(m[1])) return { tab: "home", league: null };
  const league = m[1] === "table" && m[2] && LEAGUE_RE.test(m[2]) ? m[2] : null;
  return { tab: m[1], league };
}

export function buildHash(tab, league) {
  if (!TAB_IDS.includes(tab) || tab === "home") return "";
  return tab === "table" && league && LEAGUE_RE.test(league) ? `#/table/${league}` : `#/${tab}`;
}

export function readInitial(win = typeof window !== "undefined" ? window : null) {
  try { return parseHash(win && win.location ? win.location.hash : ""); } catch (e) { return { tab: "home", league: null }; }
}

/** Update the address bar without adding history entries or reloading. */
export function writeHash(tab, league, win = typeof window !== "undefined" ? window : null) {
  try {
    if (!win || !win.history || !win.location) return;
    const next = buildHash(tab, league);
    if ((win.location.hash || "") === next) return;
    win.history.replaceState(win.history.state, "", win.location.pathname + win.location.search + next);
  } catch (e) { /* never let this break the app */ }
}
