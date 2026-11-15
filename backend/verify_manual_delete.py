"""Deleting a manual result removes it from what fans see immediately."""
import os, sys, tempfile, logging
os.environ["ADMIN_TOKEN"] = "tok-123"
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
if not os.environ.get("DATABASE_URL"):
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
import main
from fastapi.testclient import TestClient
fails = []
def check(label, ok):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok: fails.append(label)
db.init_db()
main.refresh_fixtures_results = lambda: None
H = {"x-admin-token": "tok-123"}
c = TestClient(main.app)
main.cache["standings"] = {}
main.cache["fixtures_results"] = {"fixtures": [], "live": [], "results": [
    {"league_short": "PLM", "league": "Premier League Men", "home_team": "Kenya Police", "away_team": "Parklands Sports Club",
     "home_score": 2, "away_score": 0, "date": "08-11-2026 15:00", "state": "FT", "match_url": "k1", "home_team_url": "", "away_team_url": ""}]}
body = lambda h, a, hs, as_: {"league_short": "PLM", "home_team": h, "away_team": a, "home_score": hs, "away_score": as_, "date": "2026-11-15 15:00", "venue": "Dashmesh Stadium"}
r1 = c.post("/api/admin/results/add", headers=H, json=body("USIU – A", "Sikh Union Nairobi", 1, 4)); k1 = r1.json()["match_key"]
r2 = c.post("/api/admin/results/add", headers=H, json=body("Sikh Union Nairobi", "USIU – A", 4, 1)); k2 = r2.json()["match_key"]
shown = lambda: [(m["home_team"], m["away_team"]) for m in main.cache["fixtures_results"]["results"]]
check("both manual results are showing", ("USIU – A", "Sikh Union Nairobi") in shown() and ("Sikh Union Nairobi", "USIU – A") in shown())
main.archive_current_matches()
arch = lambda: [x for x in db.load_archive_matches()] if hasattr(db, "load_archive_matches") else None
conn = db.get_connection(); n0 = conn.execute("SELECT COUNT(*) AS n FROM match_archive WHERE match_key LIKE 'PLM|%2026-11-15'").fetchone()["n"]; conn.close()
check("both archived", n0 == 2)

d1 = c.delete(f"/api/admin/results/{k1}", headers=H)
check("delete 1 ok and reports removal", d1.status_code == 200 and d1.json()["removed_from_app"] == 1)
check("deleted result gone from the app right away", ("USIU – A", "Sikh Union Nairobi") not in shown())
check("the other manual result untouched", ("Sikh Union Nairobi", "USIU – A") in shown())
check("KHU's own result untouched", ("Kenya Police", "Parklands Sports Club") in shown())
d2 = c.delete(f"/api/admin/results/{k2}", headers=H)
check("delete 2 ok", d2.status_code == 200 and ("Sikh Union Nairobi", "USIU – A") not in shown())
conn = db.get_connection(); n1 = conn.execute("SELECT COUNT(*) AS n FROM match_archive WHERE match_key LIKE 'PLM|%2026-11-15'").fetchone()["n"]; conn.close()
check("gone from the permanent archive too", n1 == 0)
check("not shown in /api/results either", all("USIU" not in (m["home_team"] + m["away_team"]) for g in [c.get("/api/results").json()] for m in (g.get("results") if isinstance(g, dict) and "results" in g else [])))

# KHU later publishes the same match itself: deleting a manual stand-in must NOT remove KHU's copy / archive
main.cache["fixtures_results"]["results"].append({"league_short": "PLM", "league": "Premier League Men", "home_team": "Sikh Union Nairobi", "away_team": "USIU – A",
    "home_score": 4, "away_score": 1, "date": "15-11-2026 15:00", "state": "FT", "match_url": "k9", "home_team_url": "", "away_team_url": ""})
r3 = c.post("/api/admin/results/add", headers=H, json=body("Sikh Union Nairobi", "USIU – A", 4, 1)); k3 = r3.json()["match_key"]
main.archive_current_matches()
c.delete(f"/api/admin/results/{k3}", headers=H)
check("KHU's own copy survives the delete", ("Sikh Union Nairobi", "USIU – A") in shown())
conn = db.get_connection(); n2 = conn.execute("SELECT COUNT(*) AS n FROM match_archive WHERE match_key LIKE 'PLM|%2026-11-15'").fetchone()["n"]; conn.close()
check("KHU's archive record survives", n2 == 1)
check("deleting an unknown key is still a 404", c.delete("/api/admin/results/nope", headers=H).status_code == 404)
print("FAILED: " + ", ".join(fails) if fails else "ALL PASS"); sys.exit(1 if fails else 0)
