"""
Offline checks for auto-retiring hand-made edits once KHU's site agrees with them.
No network.   Run:  env -u DATABASE_URL python verify_auto_retire.py
"""
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
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)

db.init_db()
U = "https://www.kenyahockeyunion.org/joomsport_team/"
SHORT = "NLM-SZ"
KEY = main.LEAGUES_BY_SHORT[SHORT]["key"]
def team(n, slug): return {"team": n, "team_url": U + slug + "/", "team_logo_url": "", "played": "5", "won": "3", "drawn": "1",
                           "lost": "1", "goals_for": "9", "goals_against": "4", "goal_diff": "5", "points": "10", "form": ["W"]}
main.cache["standings"] = {KEY: {"short": SHORT, "standings": [team("Kisii Falcons", "kisii-falcons"),
    team("Kisii University", "kisii-university"), team("Kabianga University", "kabianga-university"), team("Bay Club", "bay-club")]}}
main._pristine_standings[KEY] = list(main.cache["standings"][KEY]["standings"])

def m(home, hslug, away, aslug, date, hs, a_s, state="FT", **extra):
    d = {"league_short": SHORT, "league": "NLM Southern", "home_team": home, "home_team_url": U + hslug + "/", "home_logo_url": "",
         "away_team": away, "away_team_url": U + aslug + "/", "away_logo_url": "", "date": date, "home_score": hs,
         "away_score": a_s, "state": state, "match_url": "u"}
    d.update(extra); return d
def snapshot(*results, live=()):
    return {"fixtures": [], "live": list(live), "results": list(results)}
def manual(home, hslug, away, aslug, date, hs, a_s, **extra):
    r = {"league_short": SHORT, "home_team": home, "away_team": away, "home_team_url": U + hslug + "/",
         "away_team_url": U + aslug + "/", "home_score": hs, "away_score": a_s, "date": date, "venue": ""}
    r.update(extra); return db.save_manual_result(r)
def reset():
    for r in db.load_manual_results(): db.delete_manual_result(r["match_key"])
    for c in db.load_match_corrections(): db.delete_match_correction(c["corr_key"])
    main._retire_streak.clear(); main._manual_conflicts.clear(); main._manual_kept_for_scorers.clear(); main._retired_recently.clear()
    main._corrections_khu_matches = set()
def exists(mk): return any(r["match_key"] == mk for r in db.load_manual_results())
def run(data, shorts=(SHORT,)): return main.retire_caught_up_manual_edits(data, set(shorts))

print("1. A manual result KHU has not published stays")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
for _ in range(4): run(snapshot())
check("never published: kept after many refreshes", exists(mk))

print("2. KHU publishes the SAME score: deleted after two refreshes in a row")
khu = snapshot(m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 2, 1))
out = run(khu)
check("first agreeing refresh keeps it (one odd page must not delete)", exists(mk) and out["results_retired"] == 0)
out = run(khu)
check("second agreeing refresh deletes it", (not exists(mk)) and out["results_retired"] == 1, str(out))
check("the deletion is recorded", len(main._retired_recently) == 1 and main._retired_recently[0]["kind"] == "result")

print("3. KHU shows a DIFFERENT score: kept and flagged, never deleted")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
khu = snapshot(m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 1, 0))
for _ in range(5): out = run(khu)
check("kept after many refreshes", exists(mk))
check("conflict reported with both scores", main._manual_conflicts.get(mk) == {"khu_score": "1-0", "our_score": "2-1"}, str(main._manual_conflicts))
c = TestClient(main.app)
lst = c.get("/api/admin/results/list", headers={"x-admin-token": "tok-123"}).json()
row = next(r for r in lst["results"] if r["match_key"] == mk)
check("the admin list shows the conflict", row.get("khu_conflict", {}).get("khu_score") == "1-0")

print("4. The agreement must be unbroken (agree, disagree, agree is not enough)")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
agree = snapshot(m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 2, 1))
differ = snapshot(m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 3, 1))
run(agree); run(differ); run(agree)
check("kept: the streak was broken", exists(mk))
run(agree)
check("deleted after two in a row again", not exists(mk))

print("5. A result with goal scorers or cards is kept (KHU publishes neither)")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1,
            scorers=[{"team": "home", "player_name": "A Player", "minute": 12}])
for _ in range(4): run(agree)
check("kept", exists(mk))
check("and marked as kept for its scorers", mk in main._manual_kept_for_scorers)

print("6. Only a FULL scrape of that league counts")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
for _ in range(4): run(agree, shorts=())
for _ in range(4): run(agree, shorts=("PLM",))
check("nothing deleted when the league was not scraped completely", exists(mk))

print("7. KHU lists it but without a final score yet")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
live = snapshot(live=[m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 1, 0, state="LIVE")])
for _ in range(4): run(live)
check("kept while KHU shows it live", exists(mk))

print("8. Our own copies are not evidence")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
own = snapshot(m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 2, 1, source="manual"))
for _ in range(4): run(own)
check("a manual copy in the data never deletes the manual row", exists(mk))
corrected = snapshot(m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 2, 1, corrected=True))
for _ in range(4): run(corrected)
check("a corrected copy is not KHU's own data either", exists(mk))

print("9. The switch")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
main.AUTO_RETIRE = False
for _ in range(4): run(agree)
check("KHU_AUTO_RETIRE=0 deletes nothing", exists(mk))
main.AUTO_RETIRE = True

print("10. Match corrections")
REAL_REFRESH = main.refresh_fixtures_results
main.refresh_fixtures_results = lambda *a, **k: None   # endpoints must never start a real scrape from a test
H = {"x-admin-token": "tok-123"}
reset()
def wrong():  return snapshot(m("Kisii Falcons", "kisii-falcons", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 2, 0))
def fixed():  return snapshot(m("Kisii University", "kisii-university", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 2, 0))
body = {"league_short": SHORT, "date": "2026-09-27", "home_team": "Kisii Falcons", "away_team": "Kabianga University",
        "new_home_team": "Kisii University"}
main.cache["fixtures_results"] = wrong()
r = c.post("/api/admin/match-corrections/set", headers=H, json=body)
check("correction saved", r.status_code == 200, r.text[:80])
for _ in range(4):
    d = wrong(); main.apply_match_corrections(d); run(d)
check("KHU still wrong: the correction is kept", len(db.load_match_corrections()) == 1)
d = fixed(); main.apply_match_corrections(d)
check("KHU's fixed page is recognised as matching", len(main._corrections_khu_matches) == 1, str(main._corrections_khu_matches))
run(d)
check("kept after the first agreeing refresh", len(db.load_match_corrections()) == 1)
d = fixed(); main.apply_match_corrections(d); out = run(d)
check("deleted after the second", len(db.load_match_corrections()) == 0 and out["corrections_retired"] == 1, str(out))

print("11. A correction that hides a match is never auto-deleted")
reset()
main.cache["fixtures_results"] = wrong()
r = c.post("/api/admin/match-corrections/set", headers=H, json={"league_short": SHORT, "date": "2026-09-27",
           "home_team": "Kisii Falcons", "away_team": "Kabianga University", "hide": True})
check("hide correction saved", r.status_code == 200, r.text[:80])
for _ in range(4):
    d = wrong(); main.apply_match_corrections(d); run(d)
for _ in range(4):
    d = snapshot(); main.apply_match_corrections(d); run(d)
check("kept", len(db.load_match_corrections()) == 1)

print("12. Wired into the real refresh: only a full scrape retires, never the live-watch pass")
reset()
mk = manual("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "2026-11-14 10:00", 2, 1)
khu_match = m("Kisii Falcons", "kisii-falcons", "Bay Club", "bay-club", "14-11-2026 10:00", 2, 1)
def fake_scrape(league_key, teams):
    if league_key == KEY:
        return {"matches": [dict(khu_match)], "incomplete": False, "teams_failed": 0, "teams_fetched": len(teams)}
    return {"matches": [], "incomplete": False, "teams_failed": 0, "teams_fetched": 0}
main.scrape_league_results_via_teams = fake_scrape
main.db.save_fixtures_results = lambda *a, **k: None
main.archive_current_matches = lambda: None
main.cache["fixtures_results"] = snapshot()
for _ in range(4): REAL_REFRESH(only_team_names={"kisii falcons", "bay club"})
check("live-watch passes never delete it", exists(mk))
REAL_REFRESH()
check("first full scrape: kept", exists(mk))
REAL_REFRESH()
check("second full scrape: deleted", not exists(mk))
table_row = {r["team"]: r for r in main.cache["standings"][KEY]["standings"]}
check("KHU's own row for the match is what fans see", any(
    x.get("home_team") == "Kisii Falcons" and x.get("source") != "manual" for x in main.cache["fixtures_results"]["results"]))

print()
print("ALL CHECKS PASSED" if not fails else f"FAILED: {len(fails)} -> {fails}")
sys.exit(1 if fails else 0)
