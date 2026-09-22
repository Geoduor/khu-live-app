"""
Offline verification for the manual-results -> standings pipeline.
No network, no database writes: db reads are stubbed, cache is in-memory.

Run:  python verify_manual_results_v2.py

Checks:
  1. A manual result the live scrape hasn't published DOES move the table.
  2. Recomputing twice does NOT double-count (idempotent).
  3. Once the live scrape publishes the same match, the manual effect
     drops out automatically (site takes back over).
  4. A manual result whose teams aren't in the standings is reported,
     never guessed at.
  5. The old crash case (string stats from the scraper) does not recur.
"""
import sys
import os
import logging

# Silences APScheduler's import-time chatter; the overlay logs from
# main.py itself are kept visible because they're the useful part.
logging.getLogger("apscheduler").setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main

# ── stub the DB reads recompute touches (no real DB involved) ──
MANUAL = [{
    "match_key": "PLM|butali warriors|strathmore gladiators|2026-06-13",
    "league_short": "PLM",
    "home_team": "Butali Warriors",
    "away_team": "Strathmore Gladiators",
    "home_team_url": "https://www.kenyahockeyunion.org/joomsport_team/butali-warriors/",
    "away_team_url": "https://www.kenyahockeyunion.org/joomsport_team/strathmore-gladiators/",
    "home_score": 2,
    "away_score": 1,
    "date": "2026-06-13 15:00",
}]
main.db.load_manual_results = lambda: [dict(r) for r in MANUAL]
main.db.load_team_stats = lambda: []

# ── fake SCRAPED rows (stats as TEXT, exactly like the scraper emits) ──
PRISTINE = [
    {"position": "1", "team": "Butali Warriors", "team_url": "https://www.kenyahockeyunion.org/joomsport_team/butali-warriors/",
     "played": "9", "won": "6", "drawn": "2", "lost": "1", "goals_for": "20", "goals_against": "8",
     "goal_diff": "12", "points": "20", "form": ["W", "W", "D"]},
    {"position": "2", "team": "Strathmore Gladiators", "team_url": "https://www.kenyahockeyunion.org/joomsport_team/strathmore-gladiators/",
     "played": "9", "won": "5", "drawn": "2", "lost": "2", "goals_for": "15", "goals_against": "10",
     "goal_diff": "5", "points": "17", "form": ["W", "L", "W"]},
    {"position": "3", "team": "Kenya Police", "team_url": "https://www.kenyahockeyunion.org/joomsport_team/kenya-police/",
     "played": "9", "won": "4", "drawn": "1", "lost": "4", "goals_for": "12", "goals_against": "13",
     "goal_diff": "-1", "points": "13", "form": ["L", "W", "L"]},
]

def fresh_cache():
    main.cache["standings"]["premier_league_men"] = {
        "league": "Premier League Men", "short": "PLM",
        "standings": [dict(r) for r in PRISTINE], "total_teams": 3,
    }
    main._pristine_standings["premier_league_men"] = [dict(r) for r in PRISTINE]
    main.cache["fixtures_results"] = {"results": [], "live": [], "fixtures": []}

def table():
    return {
        t["team"]: (t["position"], t["played"], t["won"], t["points"], t["goal_diff"], tuple(t["form"]))
        for t in main.cache["standings"]["premier_league_men"]["standings"]
    }

def stats(t, team):
    """(played, won, points, goal_diff) as strings — readable asserts that
    don't care whether the values are ints or numeric strings."""
    return [str(x) for x in t[team][1:5]]

failures = []

def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)

print("1. Manual result moves the table (and does not crash on string stats)")
fresh_cache()
summary = main.recompute_league_standings("premier_league_men")
t = table()
check("result counted as applied", summary["manual_results_applied"] == 1, f"summary={summary['manual_results_applied']}")
check("Butali Warriors (2-1 home win): played 9->10, won 6->7, points 20->23, GD 12->13",
      stats(t, "Butali Warriors") == ["10", "7", "23", "13"],
      str(t["Butali Warriors"]))
check("Strathmore Gladiators (1-2 away loss): played 9->10, won 5, points 17, GD 5->4",
      stats(t, "Strathmore Gladiators") == ["10", "5", "17", "4"],
      str(t["Strathmore Gladiators"]))
check("Form was appended (W for winner, L for loser)",
      t["Butali Warriors"][5][-1] == "W" and t["Strathmore Gladiators"][5][-1] == "L")
check("Untouched team unchanged (played 9, won 4, points 13, GD -1)",
      stats(t, "Kenya Police") == ["9", "4", "13", "-1"],
      str(t["Kenya Police"]))

print("2. Recompute is idempotent (no double counting)")
before = table()
main.recompute_league_standings("premier_league_men")
main.recompute_league_standings("premier_league_men")
check("table identical after two more recomputes", table() == before)

print("3. Live catch-up: scrape publishes the same match (different date format)")
fresh_cache()
main.recompute_league_standings("premier_league_men")
main.cache["fixtures_results"]["results"] = [{
    "league_short": "PLM", "home_team": "Butali Warriors", "away_team": "Strathmore Gladiators",
    "date": "13-06-2026 15:00", "home_score": 2, "away_score": 1, "state": "FT",
}]
summary = main.recompute_league_standings("premier_league_men")
t = table()
check("manual effect dropped once published live", summary["manual_results_applied"] == 0, f"summary={summary}")
check("table reverted to the scraped numbers (played 9, points 20, GD 12)",
      stats(t, "Butali Warriors") == ["9", "6", "20", "12"], str(t["Butali Warriors"]))

print("4. Team missing from standings is reported, not guessed")
fresh_cache()
main.cache["premier_league_men"] = None  # no-op placeholder
main.db.load_manual_results = lambda: [dict(MANUAL[0], home_team="Nonexistent HC", home_team_url="", away_team="Also Missing", away_team_url="")]
summary = main.recompute_league_standings("premier_league_men")
check("unmatched teams reported", set(summary["unmatched_teams"]) == {"Nonexistent HC", "Also Missing"}, str(summary["unmatched_teams"]))
check("nothing applied", summary["manual_results_applied"] == 0)

print("5. Corrections precedence + resort sanity")
fresh_cache()
main.db.load_manual_results = lambda: [dict(r) for r in MANUAL]
main.db.load_team_stats = lambda: [{
    "stat_key": "PLM|kenya police", "league_short": "PLM", "team_name": "Kenya Police",
    "points": "99",
}]
summary = main.recompute_league_standings("premier_league_men")
t = table()
check("admin correction wins for the field it sets", str(t["Kenya Police"][3]) == "99", str(t["Kenya Police"]))
check("correction caused a resort (99 points -> position 1)", str(t["Kenya Police"][0]) == "1", str(t["Kenya Police"]))
main.db.load_team_stats = lambda: []

print()
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: all checks passed")
