"""Admin 'Add a fixture' form: validation, persistence, dedup, delete, backup/restore."""
import os, sys, tempfile, logging
from datetime import datetime, timedelta
os.environ["ADMIN_TOKEN"] = "tok-123"
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
if not os.environ.get("DATABASE_URL"):
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
import main, backup
from fastapi.testclient import TestClient
fails = []
def check(label, ok):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok: fails.append(label)
db.init_db()
main.refresh_fixtures_results = lambda *a, **k: None
H = {"x-admin-token": "tok-123"}
c = TestClient(main.app)
main.cache["standings"] = {}
tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
main.cache["fixtures_results"] = {"fixtures": [], "live": [], "results": [], "scraped_at": "2020-01-01T00:00:00", "_cache_scraped_at": "2020-01-01T00:00:00", "_cache_success": True}
body = lambda **kw: {**{"league_short": "PLM", "home_team": "Butali Warriors", "away_team": "USIU-A",
                         "date": f"{tomorrow} 10:00", "venue": "Dashmesh Stadium"}, **kw}
shown = lambda: [(m["home_team"], m["away_team"], m["date"][11:16], m.get("venue")) for m in c.get("/api/fixtures").json()["fixtures"]]

check("no token -> 401", c.post("/api/admin/fixtures/add", json=body()).status_code == 401)
check("wrong token -> 401", c.post("/api/admin/fixtures/add", headers={"x-admin-token": "nope"}, json=body()).status_code == 401)
check("list needs token", c.get("/api/admin/fixtures/list").status_code == 401)
check("delete needs token", c.delete("/api/admin/fixtures/x").status_code == 401)
check("unknown league -> 400", c.post("/api/admin/fixtures/add", headers=H, json=body(league_short="XXX")).status_code == 400)
check("same team -> 400", c.post("/api/admin/fixtures/add", headers=H, json=body(away_team="Butali Warriors")).status_code == 400)
check("bad date -> 400", c.post("/api/admin/fixtures/add", headers=H, json=body(date="tomorrow")).status_code == 400)
check("empty team -> 400", c.post("/api/admin/fixtures/add", headers=H, json=body(home_team="  ")).status_code == 400)

r = c.post("/api/admin/fixtures/add", headers=H, json=body()); key = r.json().get("match_key")
check("add ok", r.status_code == 200 and key and key.startswith("PLM|butali warriors|usiu-a|"))
check("shows in /api/fixtures right away", ("Butali Warriors", "USIU-A", "10:00", "Dashmesh Stadium") in shown())
check("scrape timestamp NOT refreshed by the add", main.cache["fixtures_results"]["_cache_scraped_at"] == "2020-01-01T00:00:00")

r = c.post("/api/admin/fixtures/add", headers=H, json=body(date=f"{tomorrow} 11:30", venue="Aryans Ground"))
check("correction accepted", r.status_code == 200)
sh = [x for x in shown() if x[0] == "Butali Warriors"]
check("correction replaces (no duplicate)", sh == [("Butali Warriors", "USIU-A", "11:30", "Aryans Ground")])
check("one stored row", len(db.load_admin_fixtures()) == 1)

# a KHU/PDF import can never overwrite the hand-entered one
db.save_pdf_fixtures([{**db.load_admin_fixtures()[0][1], "date": f"{tomorrow} 09:00", "venue": "Other"}], source_file="pdf_fixtures_seed.json")
check("seed/PDF cannot overwrite the form entry", db.load_admin_fixtures()[0][1]["venue"] == "Aryans Ground")
# but the form can overwrite a PDF one
db.save_pdf_fixtures([{**db.load_admin_fixtures()[0][1], "league_short": "PLW", "league": "Premier League Women", "home_team": "A", "away_team": "B", "added_by": None}], source_file="pdf_fixtures_seed.json")
check("clear_pdf_fixtures keeps form entries", (db.clear_pdf_fixtures(), len(db.load_admin_fixtures()))[1] == 1)

lst = c.get("/api/admin/fixtures/list", headers=H).json()
check("list shows it", lst["total"] == 1 and lst["fixtures"][0]["match_key"] == key)

# KHU publishes the same match: theirs wins, no double
main.cache["fixtures_results"]["fixtures"] = [{"league_short": "PLM", "league": "Premier League Men", "home_team": "Butali Warriors", "away_team": "USIU-A",
    "date": f"{tomorrow} 11:30", "venue": "KHU venue", "state": "NS", "match_url": "k1", "home_score": None, "away_score": None, "source": "kenyahockeyunion.org"}]
r = c.post("/api/admin/fixtures/add", headers=H, json=body(date=f"{tomorrow} 11:30"))
check("flags that KHU already lists it", r.status_code == 200 and r.json()["already_listed_by_khu"] is True)
check("only one copy shown, KHU's", [x for x in shown() if x[0] == "Butali Warriors"] == [("Butali Warriors", "USIU-A", "11:30", "KHU venue")])

# an already-played match is refused
main.cache["fixtures_results"]["results"] = [{"league_short": "PLM", "home_team": "Kenya Police", "away_team": "Parklands Sports Club",
    "date": f"{tomorrow} 15:00", "home_score": 1, "away_score": 0, "state": "FT"}]
check("played match -> 409", c.post("/api/admin/fixtures/add", headers=H, json=body(home_team="Kenya Police", away_team="Parklands Sports Club", date=f"{tomorrow} 15:00")).status_code == 409)
main.cache["fixtures_results"]["fixtures"] = []; main.cache["fixtures_results"]["results"] = []

# backup / restore round trip
bk = backup.build_backup()
check("backup contains the added fixture", len(bk["added_fixtures"]) == 1)
c.post("/api/admin/fixtures/add", headers=H, json=body())
check("(setup) fixture is showing before delete", any(x[0] == "Butali Warriors" for x in shown()))
d = c.delete(f"/api/admin/fixtures/{key}", headers=H)
check("delete reports it was removed from the app", d.json().get("removed_from_app") == 1)
check("delete ok", d.status_code == 200 and not db.load_admin_fixtures())
check("gone from the app (cache)", all(x[0] != "Butali Warriors" for x in shown()))
check("second delete -> 404", c.delete(f"/api/admin/fixtures/{key}", headers=H).status_code == 404)
rs = c.post("/api/admin/restore", headers=H, json=bk)
check("restore ok and brings it back", rs.status_code == 200 and len(db.load_admin_fixtures()) == 1)
check("damaged backup row is skipped, not fatal", c.post("/api/admin/restore", headers=H, json={"added_fixtures": [{"league_short": "ZZZ"}]}).status_code in (200, 400, 422))

# KHU's own PDF fixture can't be deleted through this endpoint
db.save_pdf_fixtures([{"league_short": "PLM", "league": "Premier League Men", "home_team": "Kenya Police", "away_team": "Strathmore Gladiators",
                       "date": f"{tomorrow} 14:00", "state": "NS", "source": "pdf"}], source_file="pdf_fixtures_seed.json")
pk = main._match_key({"league_short": "PLM", "home_team": "Kenya Police", "away_team": "Strathmore Gladiators", "date": f"{tomorrow} 14:00"})
check("PDF fixture can't be deleted via the form endpoint", c.delete(f"/api/admin/fixtures/{pk}", headers=H).status_code == 404
      and any(m["home_team"] == "Kenya Police" for m in db.load_pdf_fixtures()))

print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
