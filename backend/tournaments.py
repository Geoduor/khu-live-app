"""
tournaments.py — pure logic for the Tournaments feature (no I/O).

Tournaments are deliberately kept SEPARATE from league data: they have
their own tables, their own endpoints, and are never merged into league
standings, fixtures or results. A tournament is a named event (e.g. a
festival or cup) with matches grouped into stages ("Group A",
"Semi-final", "Final"); group tables are computed here from the matches
so they can never disagree with the scores shown beside them.
"""
import re
from datetime import datetime

_DATE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d")
VALID_STATUS = ("upcoming", "ongoing", "completed")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "tournament"


def parse_date(value: str):
    """Parse the date strings admin/agent forms send. None if blank/bad."""
    value = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def validate_match(m: dict) -> str:
    """Return an error message, or '' if the match is acceptable."""
    home, away = (m.get("home_team") or "").strip(), (m.get("away_team") or "").strip()
    if not home or not away:
        return "Both team names are required."
    if home.lower() == away.lower():
        return "Home and away team can't be the same."
    hs, aws = m.get("home_score"), m.get("away_score")
    if (hs is None) != (aws is None):
        return "Enter both scores, or leave both empty for an upcoming match."
    for sc in (hs, aws):
        if sc is not None and (not isinstance(sc, int) or sc < 0 or sc > 99):
            return "Scores must be whole numbers between 0 and 99."
    if m.get("date") and not parse_date(m["date"]):
        return "Date must look like 2026-10-10 or 2026-10-10 14:30."
    return ""


def match_state(m: dict) -> str:
    return "FT" if m.get("home_score") is not None and m.get("away_score") is not None else "NS"


def compute_group_tables(matches: list) -> list:
    """Group tables from played matches that have a group_name.
    3-1-0 points (same rule as the leagues). Returns
    [{"group": "Group A", "rows": [{team, played, won, drawn, lost,
    goals_for, goals_against, goal_diff, points}]}], groups sorted by name.
    Teams are keyed case-insensitively so 'Kisumu Queens' and
    'kisumu queens' are one team; the first-seen spelling is displayed."""
    groups = {}
    for m in matches:
        g = (m.get("group_name") or "").strip()
        if not g:
            continue
        table = groups.setdefault(g, {})
        for name in (m["home_team"], m["away_team"]):  # teams appear even before playing
            table.setdefault(name.strip().lower(), {
                "team": name.strip(), "played": 0, "won": 0, "drawn": 0, "lost": 0,
                "goals_for": 0, "goals_against": 0, "goal_diff": 0, "points": 0,
            })
        if match_state(m) != "FT":
            continue
        h = table[m["home_team"].strip().lower()]
        a = table[m["away_team"].strip().lower()]
        hs, aws = m["home_score"], m["away_score"]
        for row, gf, ga in ((h, hs, aws), (a, aws, hs)):
            row["played"] += 1
            row["goals_for"] += gf
            row["goals_against"] += ga
            row["goal_diff"] = row["goals_for"] - row["goals_against"]
        if hs > aws:
            h["won"] += 1; h["points"] += 3; a["lost"] += 1
        elif hs < aws:
            a["won"] += 1; a["points"] += 3; h["lost"] += 1
        else:
            h["drawn"] += 1; a["drawn"] += 1; h["points"] += 1; a["points"] += 1
    out = []
    for g in sorted(groups):
        rows = sorted(groups[g].values(),
                      key=lambda r: (-r["points"], -r["goal_diff"], -r["goals_for"], r["team"].lower()))
        for i, r in enumerate(rows, 1):
            r["position"] = i
        out.append({"group": g, "rows": rows})
    return out


_PLACEHOLDER_RE = re.compile(r"^(winner|loser)\b|^\d+(st|nd|rd|th)\s+position$|^tbc$|^tbd$", re.I)


def is_placeholder_team(name: str) -> bool:
    """'Winner QF 1', 'Loser SF 2', '1st Position' — slots, not real teams."""
    return bool(_PLACEHOLDER_RE.search((name or "").strip()))


def stage_prefix(stage: str) -> str:
    """'Men – Pool' -> 'Men'. Stages without ' – ' share one roster ('')."""
    st = (stage or "").strip()
    return st.split(" – ")[0].strip() if " – " in st else ""


def build_rosters(matches: list) -> dict:
    """{prefix: sorted real team names}. Teams come from group (pool) matches
    when any exist, otherwise from every non-placeholder name. Used to turn
    free-text team boxes into dropdowns so spelling can't drift."""
    rosters = {}
    have_groups = any((m.get("group_name") or "").strip() for m in matches)
    for m in matches:
        if have_groups and not (m.get("group_name") or "").strip():
            continue
        r = rosters.setdefault(stage_prefix(m.get("stage") or m.get("group_name") or ""), {})
        for nm in (m["home_team"], m["away_team"]):
            nm = nm.strip()
            if nm and not is_placeholder_team(nm):
                r.setdefault(nm.lower(), nm)
    return {k: sorted(v.values(), key=str.lower) for k, v in rosters.items()}


def build_tournament_detail(tournament: dict, matches: list) -> dict:
    """Public payload for one tournament: matches with state, ordered
    stages in chronological order (opening game first, Final last), and
    computed group tables."""
    ms = []
    for m in matches:
        d = dict(m)
        d["state"] = match_state(m)
        d["stage"] = (m.get("stage") or m.get("group_name") or "Matches").strip()
        ms.append(d)

    def ts(m):
        p = parse_date(m.get("date", ""))
        return p.timestamp() if p else 0

    # Chronological: stages ordered by their FIRST kickoff, so the list reads
    # from the opening game to the final. Undated stages go last.
    stage_first = {}
    for m in ms:
        t = ts(m) or float("inf")
        stage_first[m["stage"]] = min(stage_first.get(m["stage"], float("inf")), t)
    stages = sorted(stage_first, key=lambda s: (stage_first[s], s))
    ms.sort(key=lambda m: (stages.index(m["stage"]), ts(m)))
    return {
        "tournament": tournament,
        "matches": ms,
        "stages": stages,
        "group_tables": compute_group_tables(matches),
        "rosters": build_rosters(matches),
        "totals": {"matches": len(ms), "played": sum(1 for m in ms if m["state"] == "FT")},
    }
