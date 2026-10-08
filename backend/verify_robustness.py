"""
Offline checks for the failure-handling / auth fixes. No network.
Run:  python verify_robustness.py
"""
import os, sys, tempfile, logging
os.environ["ADMIN_TOKEN"] = "tok-123"
os.environ["ADMIN_USERNAME"] = "boss"
os.environ["ADMIN_PASSWORD"] = "pw-pw-pw"
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db") if hasattr(db, "DB_PATH") else None
import main
from fastapi.testclient import TestClient

fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)

db.init_db()

print("1. Blocked scrape keeps last-known-good matches")
good = {"league_short": "PLM", "home_team": "A", "away_team": "B", "date": "01-06-2026 15:00",
        "home_score": 1, "away_score": 0, "state": "FT", "match_url": "u1"}
main.cache["fixtures_results"] = {"results": [good], "fixtures": [], "live": []}
main.cache["standings"]["premier_league_men"] = {"standings": [{"team": "A", "team_url": "x"}], "short": "PLM"}
for k in list(main.LEAGUES):
    if k != "premier_league_men":
        main.cache["standings"].pop(k, None)
main.scrape_league_results_via_teams = lambda k, t: {"matches": [], "total": 0, "incomplete": True, "teams_failed": 2}
ok = main.refresh_fixtures_results()
res = main.cache["fixtures_results"]["results"]
check("previous result still served", any(m["match_url"] == "u1" for m in res), f"{len(res)} results")
check("cycle reported as NOT successful", ok is False)
check("league flagged stale", "premier_league_men" in main.cache["fixtures_results"]["stale_leagues"])

print("2. Complete scrape counts as success")
main.scrape_league_results_via_teams = lambda k, t: {"matches": [dict(good, match_url="u2")], "total": 1, "incomplete": False}
check("success when fresh data scraped", main.refresh_fixtures_results() is True)

print("3. Agent accounts survive a 'cold start' via AGENTS_SEED")
db.create_agent("jane", "secret12", "Jane")
c = TestClient(main.app)
seed = c.get("/api/admin/agents/export-seed", headers={"x-admin-token": "tok-123"}).json()["agents"]
check("export works with admin token", len(seed) == 1 and "password_hash" in seed[0])
check("export refused without token", c.get("/api/admin/agents/export-seed").status_code == 401)
conn = db.get_connection(); conn.execute("DELETE FROM agents"); conn.commit(); conn.close()
import json
os.environ["AGENTS_SEED"] = json.dumps(seed)
main.seed_agents_from_env()
check("agent can log in after restore", db.verify_agent_login("jane", "secret12") == "Jane")
main.seed_agents_from_env()
check("re-seeding is idempotent", len(db.list_agents()) == 1)

print("4. Login throttle")
codes = [c.post("/api/admin/login", json={"username": "boss", "password": "bad"}).status_code for _ in range(6)]
check("5 wrong tries -> 401, 6th -> 429", codes == [401]*5 + [429], str(codes))
main._login_failures.clear()
check("correct login works after reset", c.post("/api/admin/login", json={"username": "boss", "password": "pw-pw-pw"}).status_code == 200)

print("5. Constant-time token check")
check("good token", main._is_admin("tok-123")); check("bad token", not main._is_admin("nope")); check("empty token", not main._is_admin(""))

print("6. Tournaments are separate from league data")
H={"x-admin-token": "tok-123"}
r=c.post("/api/admin/tournaments/save", headers=H, json={"name":"Kisumu Festival 2026","start_date":"2026-10-10","status":"ongoing"})
tid=r.json().get("id"); check("create tournament", r.status_code==200 and tid=="kisumu-festival-2026", str(r.json()))
check("save refused without token", c.post("/api/admin/tournaments/save", json={"name":"x"}).status_code==401)
def addm(**k):
    d={"stage":"Group A","group_name":"Group A","date":"2026-10-10 10:00"}; d.update(k)
    return c.post(f"/api/admin/tournaments/{tid}/matches/save", headers=H, json=d)
check("A 2-0 B", addm(home_team="Alpha",away_team="Beta",home_score=2,away_score=0).status_code==200)
check("Beta 1-1 Gamma", addm(home_team="Beta",away_team="gamma",home_score=1,away_score=1,date="2026-10-11 10:00").status_code==200)
check("upcoming match ok", addm(home_team="Alpha",away_team="Gamma",date="2026-10-12 10:00").status_code==200)
check("final saved", addm(home_team="Alpha",away_team="Beta",home_score=3,away_score=2,stage="Final",group_name="",date="2026-10-13 15:00").status_code==200)
check("same team rejected", addm(home_team="A",away_team="a").status_code==400)
check("one score rejected", addm(home_team="A",away_team="B",home_score=1).status_code==400)
d=c.get(f"/api/tournaments/{tid}").json()
tbl=d["group_tables"][0]["rows"]
check("table: Alpha 3 pts, GD +2, first", tbl[0]["team"]=="Alpha" and tbl[0]["points"]==3 and tbl[0]["goal_diff"]==2, str(tbl[0]))
check("table: Beta 1 pt, Gamma 1 pt, case-insensitive team merge", len(tbl)==3 and tbl[1]["points"]==1 and tbl[2]["points"]==1, str([r["team"] for r in tbl]))
check("final stage listed first", d["stages"][0]=="Final", str(d["stages"]))
check("final not in group table", sum(r["played"] for r in tbl)==4)
check("list endpoint counts", c.get("/api/tournaments").json()["tournaments"][0]["matches_total"]==4)
check("league standings untouched", "premier_league_men" in main.cache["standings"] and len(main.cache["standings"]["premier_league_men"]["standings"])==1)
seedj=c.get("/api/admin/tournaments/export-seed", headers=H).json()
check("export has data", len(seedj["tournaments"])==1 and len(seedj["matches"])==4)
conn=db.get_connection(); conn.execute("DELETE FROM tournaments"); conn.execute("DELETE FROM tournament_matches"); conn.commit(); conn.close()
check("seed restore", db.import_tournaments_seed(seedj["tournaments"], seedj["matches"])==1 and len(db.load_tournament_matches(tid))==4)
check("delete tournament", c.delete(f"/api/admin/tournaments/{tid}", headers=H).status_code==200 and c.get(f"/api/tournaments/{tid}").status_code==404)

print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
