"""A league set to 'build from results' gets a table that agrees with its matches."""
import os, sys, logging, copy
logging.getLogger("apscheduler").setLevel(logging.WARNING)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n); fails += (not c)

KEY = main.LEAGUES_BY_SHORT["NLM-SZ"]["key"]
U = lambda n: f"https://www.kenyahockeyunion.org/joomsport_team/{n}/"
def row(i, name, p, w, d, l, gf, ga, pts):
    return {"position": str(i), "team": name, "team_url": U(name.lower().replace(" ", "-")),
            "played": str(p), "won": str(w), "drawn": str(d), "lost": str(l),
            "goals_for": str(gf), "goals_against": str(ga), "goal_diff": str(gf - ga),
            "points": str(pts), "form": []}
# KHU's table: Falcons wrongly at 13 played
PRISTINE = [row(1, "Kisii Falcons", 13, 9, 2, 2, 44, 9, 29), row(2, "Bay Club", 10, 8, 1, 1, 30, 7, 25),
            row(3, "Kisii University", 7, 4, 2, 1, 20, 4, 14)]
def M(h, a, hs, as_, date, state="FT"):
    return {"home_team": h, "away_team": a, "home_score": hs, "away_score": as_, "state": state, "date": date,
            "league_short": "NLM-SZ", "home_team_url": U(h.lower().replace(" ", "-")),
            "away_team_url": U(a.lower().replace(" ", "-"))}
RESULTS = [M("Kisii Falcons", "Bay Club", 1, 3, "01-11-2026"), M("Kisii Falcons", "Kisii University", 3, 1, "18-10-2026"),
           M("Kisii Falcons", "Bay Club", 1, 3, "01-11-2026"),  # duplicate listing
           M("Bay Club", "Kisii University", 0, 0, "20-10-2026"), M("Bay Club", "Kisii Falcons", 2, 2, "02-10-2026", state="NS")]
main.cache["fixtures_results"] = {"results": RESULTS, "fixtures": [], "live": []}
main.cache["standings"] = {KEY: {"standings": copy.deepcopy(PRISTINE)}}
main._pristine_standings[KEY] = copy.deepcopy(PRISTINE)
MODES = set()
main.db.load_derived_leagues = lambda: set(MODES)
main.db.load_manual_results = lambda: []
main.db.load_team_stats = lambda: []
main.db.load_match_corrections = lambda: []

main.recompute_league_standings(KEY)
check("off: KHU numbers kept", main.cache["standings"][KEY]["standings"][0]["played"] == "13")
check("off: table_mode khu", main.cache["standings"][KEY]["table_mode"] == "khu")

MODES.add("NLM-SZ")
s = main.recompute_league_standings(KEY)
rows = {r["team"]: r for r in main.cache["standings"][KEY]["standings"]}
f = rows["Kisii Falcons"]
check("Falcons: 2 played (dup + unplayed ignored)", f["played"] == "2")
check("Falcons: 1W 0D 1L, GF 4 GA 4, 3 pts", (f["won"], f["drawn"], f["lost"], f["goals_for"], f["goals_against"], f["points"]) == ("1", "0", "1", "4", "4", "3"))
check("Falcons: GD 0, form oldest->newest", f["goal_diff"] == "0" and f["form"] == ["W", "L"])
b = rows["Bay Club"]
check("Bay: 2 played, 1W 1D, 4 pts, GD +2", (b["played"], b["won"], b["drawn"], b["points"], b["goal_diff"]) == ("2", "1", "1", "4", "2"))
check("sorted by points then GD", [r["team"] for r in main.cache["standings"][KEY]["standings"]] == ["Bay Club", "Kisii Falcons", "Kisii University"] or
      [r["team"] for r in main.cache["standings"][KEY]["standings"]][0] == "Bay Club")
check("table_mode from_results", s["table_mode"] == "from_results")
check("pristine copy untouched", main._pristine_standings[KEY][0]["played"] == "13")

# idempotent
a = copy.deepcopy(main.cache["standings"][KEY]["standings"]); main.recompute_league_standings(KEY)
check("idempotent", a == main.cache["standings"][KEY]["standings"])

# admin absolute override still wins
main.db.load_team_stats = lambda: [{"league_short": "NLM-SZ", "team_name": "Bay Club", "points": 99, "stat_key": "NLM-SZ|bay club"}]
main.recompute_league_standings(KEY)
check("admin override wins", {r["team"]: r for r in main.cache["standings"][KEY]["standings"]}["Bay Club"]["points"] == "99")
main.db.load_team_stats = lambda: []

# no results -> never zero the table
main.cache["fixtures_results"] = {"results": [], "fixtures": [], "live": []}
main.recompute_league_standings(KEY)
check("no results: falls back to KHU table", main.cache["standings"][KEY]["standings"][0]["played"] == "13"
      and main.cache["standings"][KEY]["table_mode"] == "khu")

# endpoints
from fastapi.testclient import TestClient
saved = {}
main.db.set_derived_league = lambda s, on: (MODES.add(s) if on else MODES.discard(s))
main._status_changed = lambda: None
main.ADMIN_TOKEN = "tok"
c = TestClient(main.app)
check("set needs admin", c.post("/api/admin/table-mode/set", json={"league_short": "PLM", "from_results": True}).status_code == 401)
check("unknown league 400", c.post("/api/admin/table-mode/set", headers={"x-admin-token": "tok"}, json={"league_short": "ZZZ", "from_results": True}).status_code == 400)
r = c.post("/api/admin/table-mode/set", headers={"x-admin-token": "tok"}, json={"league_short": "PLM", "from_results": True})
check("set ok", r.status_code == 200 and "PLM" in MODES)
l = c.get("/api/admin/table-mode/list", headers={"x-admin-token": "tok"}).json()["leagues"]
check("list reflects", {x["league_short"]: x["from_results"] for x in l}["PLM"] is True)

# team profile is never stale and agrees whichever way it is opened
fails2 = 0
main.cache["fixtures_results"] = {"results": [M("Kisii Falcons", "Bay Club", 1, 3, "01-11-2026")], "fixtures": [], "live": []}
MODES.discard("NLM-SZ")
c2 = TestClient(main.app)
def prof(**kw):
    return c2.get("/api/team", params=kw).json()
a = prof(url=U("kisii-falcons"), name="Kisii Falcons", league="NLM-SZ")
check("profile shows the result", len(a["recent_results"]) == 1)
main.cache["fixtures_results"]["results"].append(M("Kisii Falcons", "Kisii University", 3, 1, "18-10-2026"))
b = prof(url=U("kisii-falcons"), name="Kisii Falcons", league="NLM-SZ")
check("new result shows immediately (no stale cache)", len(b["recent_results"]) == 2)
d = prof(url=U("kisii-falcons") + "?sid=3634", name="Kisii Falcons ", league="NLM-SZ")
check("other entry path agrees", len(d["recent_results"]) == 2)
print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
