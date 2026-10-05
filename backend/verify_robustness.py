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

print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
