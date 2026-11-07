"""
Offline checks for match corrections (fixing KHU's own mistakes for our fans).
No network.   Run:  python verify_match_corrections.py
"""
import os, sys, tempfile, logging, copy
os.environ["ADMIN_TOKEN"] = "tok-123"
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
if not os.environ.get("DATABASE_URL"):
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
import main
from fastapi.testclient import TestClient

fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)

db.init_db()
U = "https://www.kenyahockeyunion.org/joomsport_team/"
def team(n, slug): return {"team": n, "team_url": U + slug + "/", "team_logo_url": "logo-" + slug,
                           "played": "5", "won": "3", "drawn": "1", "lost": "1", "goals_for": "9", "goals_against": "4",
                           "goal_diff": "5", "points": "10", "form": ["W"]}
main.cache["standings"] = {main.LEAGUES_BY_SHORT["NLM-SZ"]["key"]: {"short": "NLM-SZ", "standings": [
    team("Kisii Falcons", "kisii-falcons"), team("Kisii University", "kisii-university"),
    team("Kabianga University", "kabianga-university"), team("Bay Club", "bay-club")]}}
def m(home, hslug, away, aslug, date, hs, a_s, url):
    return {"league_short": "NLM-SZ", "league": "NLM Southern", "home_team": home, "home_team_url": U + hslug + "/",
            "home_logo_url": "", "away_team": away, "away_team_url": U + aslug + "/", "away_logo_url": "",
            "date": date, "home_score": hs, "away_score": a_s, "state": "FT", "match_url": url}
def scraped():
    return {"fixtures": [], "live": [], "results": [
        # KHU's mistakes: these two are really Kisii University's home matches
        m("Kisii Falcons", "kisii-falcons", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 2, 0, "u1"),
        m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "17-10-2026 11:00", 0, 2, "u2"),
        # a genuine Falcons match that must be left alone
        m("Kisii Falcons", "kisii-falcons", "Kisii University", "kisii-university", "18-10-2026 10:00", 3, 1, "u3"),
    ]}

c = TestClient(main.app)
H = {"x-admin-token": "tok-123"}

print("1. Auth and validation")
body = {"league_short": "NLM-SZ", "date": "2026-09-27", "home_team": "Kisii Falcons", "away_team": "Kabianga University",
        "new_home_team": "Kisii University"}
check("refused without admin token", c.post("/api/admin/match-corrections/set", json=body).status_code == 401)
check("list refused without token", c.get("/api/admin/match-corrections/list").status_code == 401)
check("delete refused without token", c.delete("/api/admin/match-corrections/x").status_code == 401)
check("export refused without token", c.get("/api/admin/match-corrections/export-seed").status_code == 401)
r = c.post("/api/admin/match-corrections/set", headers=H, json={**body, "new_home_team": "Kisii Uni Mens"})
check("unknown replacement team rejected (never guessed)", r.status_code == 400, r.text[:90])
r = c.post("/api/admin/match-corrections/set", headers=H, json={k: body[k] for k in ("league_short", "date", "home_team", "away_team")})
check("a correction that changes nothing is rejected", r.status_code == 400)
r = c.post("/api/admin/match-corrections/set", headers=H, json={**body, "new_home_score": 1})
check("one score alone is rejected", r.status_code == 400)
r = c.post("/api/admin/match-corrections/set", headers=H, json={**body, "date": "banana"})
check("bad date rejected", r.status_code == 400)
r = c.post("/api/admin/match-corrections/set", headers=H, json={**body, "league_short": "XX"})
check("unknown league rejected", r.status_code == 400)

print("2. The Kisii case: two matches move from Falcons to University")
main.cache["fixtures_results"] = scraped()
# archive already holds the wrong copies (it keeps everything it ever saw)
main.archive_current_matches()
before = main.build_team_profile_from_cache("Kisii Falcons", U + "kisii-falcons/", "NLM-SZ")
check("before: Falcons wrongly listed with 3 results", before["season_summary"]["matches_listed"] == 3)
for b in (body, {"league_short": "NLM-SZ", "date": "17-10-2026", "home_team": "Kisii Falcons", "away_team": "Bay Club",
                 "new_home_team": "Kisii University"}):
    r = c.post("/api/admin/match-corrections/set", headers=H, json=b)
    check("saved and applied right away", r.status_code == 200 and r.json()["applied_now"], r.text[:100])
fal = main.build_team_profile_from_cache("Kisii Falcons", U + "kisii-falcons/", "NLM-SZ")
uni = main.build_team_profile_from_cache("Kisii University", U + "kisii-university/", "NLM-SZ")
check("Falcons now has only its own match", fal["season_summary"]["matches_listed"] == 1
      and fal["recent_results"][0]["opponent"] == "Kisii University", str(fal["season_summary"]))
check("University gained both matches (3 listed)", uni["season_summary"]["matches_listed"] == 3,
      str(uni["season_summary"]))
opp = sorted(r["opponent"] for r in uni["recent_results"])
check("University's opponents are Kabianga, Bay Club, Falcons", opp == ["Bay Club", "Kabianga University", "Kisii Falcons"], str(opp))
fixed = next(x for x in main.cache["fixtures_results"]["results"] if x["match_url"] == "u1")
check("team link and logo follow the new team", fixed["home_team_url"].endswith("kisii-university/") and fixed["home_logo_url"] == "logo-kisii-university")
check("score and the other team untouched", (fixed["home_score"], fixed["away_score"], fixed["away_team"]) == (2, 0, "Kabianga University"))
keys = [r["match_key"] for r in db.query_match_archive(league="NLM-SZ", limit=50)["items"]] if "items" in db.query_match_archive(league="NLM-SZ", limit=50) else []
arch = db.load_match_archive()
wrong = [a for a in arch if a["match_key"].startswith("NLM-SZ|kisii falcons|kabianga university")
         or a["match_key"].startswith("NLM-SZ|kisii falcons|bay club")]
check("wrong copies removed from the permanent archive", not wrong, str([a["match_key"] for a in wrong]))

print("3. Stays applied across every refresh (scrape rebuilds from scratch)")
for i in range(2):
    d = scraped(); n = main.apply_match_corrections(d)
    check(f"re-scrape #{i+1}: both corrections applied again", n == 2, str(n))
check("a match nobody corrected is untouched", any(x["match_url"] == "u3" and x["home_team"] == "Kisii Falcons" for x in d["results"]))
n = main.apply_match_corrections(d)
check("applying twice is harmless", n == 0 and len(d["results"]) == 3)

print("4. Goes quiet when KHU fixes its own page")
fixed_by_khu = {"fixtures": [], "live": [], "results": [
    m("Kisii University", "kisii-university", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 2, 0, "u1"),
    m("Kisii University", "kisii-university", "Bay Club", "bay-club", "17-10-2026 11:00", 0, 2, "u2")]}
snap = copy.deepcopy(fixed_by_khu)
n = main.apply_match_corrections(fixed_by_khu)
check("nothing changed once KHU is right", n == 0 and fixed_by_khu == snap)
lst = c.get("/api/admin/match-corrections/list", headers=H).json()
check("admin list says 'not needed now'", lst["count"] == 2 and not any(x["applied_now"] for x in lst["corrections"]))

print("5. Other fixes: score, hide, date")
main.cache["fixtures_results"] = scraped()
r = c.post("/api/admin/match-corrections/set", headers=H, json={"league_short": "NLM-SZ", "date": "2026-10-18",
          "home_team": "Kisii Falcons", "away_team": "Kisii University", "new_home_score": 4, "new_away_score": 1,
          "new_date": "2026-10-19 12:30"})
x = next(v for v in main.cache["fixtures_results"]["results"] if v["match_url"] == "u3")
check("score and date corrected", (x["home_score"], x["away_score"], x["date"]) == (4, 1, "19-10-2026 12:30"), str((x["home_score"], x["date"])))
check("marked as corrected", x.get("corrected") is True)
r = c.post("/api/admin/match-corrections/set", headers=H, json={"league_short": "NLM-SZ", "date": "27-09-2026",
          "home_team": "Kisii University", "away_team": "Kabianga University", "hide": True})
check("hide saved", r.status_code == 200)
d = {"fixtures": [], "live": [], "results": [m("Kisii University", "kisii-university", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 2, 0, "u1")]}
main.apply_match_corrections(d)
check("hidden match is dropped", d["results"] == [])
n0 = c.get("/api/admin/match-corrections/list", headers=H).json()["count"]
r = c.post("/api/admin/match-corrections/set", headers=H, json={"league_short": "nlm-sz", "date": "2026-09-27",
          "home_team": " kisii  UNIVERSITY ", "away_team": "kabianga university", "hide": True})
check("league/spacing/case variants replace the same correction (no duplicate)",
      r.status_code == 200 and c.get("/api/admin/match-corrections/list", headers=H).json()["count"] == n0)

print("6. Partial scrape does not duplicate the corrected match")
db.delete_match_correction  # exists
for k in [x["corr_key"] for x in db.load_match_corrections()]: db.delete_match_correction(k)
db.save_match_correction(main._correction_key("NLM-SZ", "Kisii Falcons", "Bay Club", "2026-10-17"),
    {"league_short": "NLM-SZ", "date": "2026-10-17", "home_team": "Kisii Falcons", "away_team": "Bay Club", "new_home_team": "Kisii University"})
d = scraped()
carried = m("Kisii University", "kisii-university", "Bay Club", "bay-club", "17-10-2026 11:00", 0, 2, "u2")
carried["corrected"] = True
d["results"].append(carried)
main.apply_match_corrections(d)
same = [x for x in d["results"] if x["match_url"] == "u2"]
check("exactly one copy", len(same) == 1 and same[0]["home_team"] == "Kisii University", str(len(same)))

print("7. Delete, export and backup/restore")
key = main._correction_key("NLM-SZ", "Kisii Falcons", "Bay Club", "2026-10-17")
exp = c.get("/api/admin/match-corrections/export-seed", headers=H).json()
check("export lists it", exp["count"] == 1)
import backup
check("included in the off-site backup", len(backup.build_backup()["match_corrections"]) == 1)
main.refresh_fixtures_results = lambda: None   # do not start a real scrape
check("delete works", c.delete("/api/admin/match-corrections/" + key, headers=H).status_code == 200)
check("delete again is 404", c.delete("/api/admin/match-corrections/" + key, headers=H).status_code == 404)
r = c.post("/api/admin/restore", headers=H, content=__import__("json").dumps({"match_corrections": exp["corrections"]}))
check("restore brings it back", r.status_code == 200 and r.json()["restored"].get("match_corrections") == 1, r.text[:120])
check("restored correction is stored", len(db.load_match_corrections()) == 1)

print("8. Damaged or hostile backup / stored data cannot break refreshes")
import json as _j
for k in [x["corr_key"] for x in db.load_match_corrections()]: db.delete_match_correction(k)
good = {"league_short": "NLM-SZ", "date": "2026-10-17", "home_team": "Kisii Falcons", "away_team": "Bay Club", "new_home_team": "Kisii University"}
bad_list = [
    {**good, "new_home_score": "abc", "new_away_score": "x"},          # scores that are not numbers
    {**good, "new_home_score": 3},                                       # one score only
    {**good, "new_home_score": 500, "new_away_score": 1},                # absurd score
    {**good, "league_short": "ZZ"}, {**good, "date": "never"}, {**good, "home_team": ""},
    {**good, "new_venue": "x" * 5000}, {"league_short": "NLM-SZ"}, "not a dict", 42,
    {k: v for k, v in good.items() if k != "new_home_team"},             # changes nothing
]
r = c.post("/api/admin/restore", headers=H, content=_j.dumps({"match_corrections": bad_list}))
check("restore accepts the request but stores none of the damaged entries", r.status_code == 200 and not db.load_match_corrections(), r.text[:140])
r = c.post("/api/admin/restore", headers=H, content=_j.dumps({"match_corrections": [{**good, "corr_key": "../../evil", "entered_at": "x", "extra": "<script>"}]}))
stored = db.load_match_corrections()
check("a good entry is stored under a key we compute, with unknown fields dropped",
      len(stored) == 1 and stored[0]["corr_key"] == main._correction_key("NLM-SZ", "Kisii Falcons", "Bay Club", "2026-10-17") and "extra" not in stored[0], str(stored)[:160])
# even if bad data got into the table some other way, a refresh must carry on
for k in [x["corr_key"] for x in db.load_match_corrections()]: db.delete_match_correction(k)
db.save_match_correction(main._correction_key("NLM-SZ", "Kisii Falcons", "Bay Club", "2026-10-17"), {**good, "new_home_score": "abc", "new_away_score": "x"})
db.save_match_correction("junk", {"league_short": "NLM-SZ"})
main.cache["fixtures_results"] = scraped(); main.archive_current_matches()
d = scraped()
try:
    n = main.apply_match_corrections(d); crashed = False
except Exception:
    crashed = True
check("a stored correction with bad values never crashes a refresh", not crashed and n == 0)
check("and the match is left exactly as KHU shows it", any(x["match_url"] == "u2" and x["home_team"] == "Kisii Falcons" for x in d["results"]))
check("and its archive record is kept (not purged for a correction that failed)",
      any(a["match_key"].startswith("NLM-SZ|kisii falcons|bay club") for a in db.load_match_archive()))

print()
print("ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
