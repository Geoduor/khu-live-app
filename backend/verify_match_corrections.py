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

main.refresh_fixtures_results = lambda: None   # never start a real scrape from a test
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

print("4. Keeps applying until KHU's page matches ours, then says so")
fixed_by_khu = {"fixtures": [], "live": [], "results": [
    m("Kisii University", "kisii-university", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 2, 0, "u1"),
    m("Kisii University", "kisii-university", "Bay Club", "bay-club", "17-10-2026 11:00", 0, 2, "u2")]}
before = [(x["home_team"], x["away_team"], x["home_score"], x["away_score"], x["date"]) for x in fixed_by_khu["results"]]
n = main.apply_match_corrections(fixed_by_khu)
after = [(x["home_team"], x["away_team"], x["home_score"], x["away_score"], x["date"]) for x in fixed_by_khu["results"]]
check("once KHU shows the same, nothing visible changes", sorted(before) == sorted(after) and len(fixed_by_khu["results"]) == 2, f"{before} -> {after}")
lst = c.get("/api/admin/match-corrections/list", headers=H).json()
check("admin list says 'KHU now shows the same'", lst["count"] == 2 and all(x["khu_matches"] for x in lst["corrections"]), str(lst)[:200])

# KHU moves the teams but still has a different score: OUR score stays until KHU matches ours
for body in ({"league_short": "NLM-SZ", "date": "2026-09-27", "home_team": "Kisii Falcons", "away_team": "Kabianga University", "new_home_team": "Kisii University", "new_home_score": 2, "new_away_score": 0},):
    c.post("/api/admin/match-corrections/set", headers=H, json=body)
half = {"fixtures": [], "live": [], "results": [m("Kisii University", "kisii-university", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 3, 0, "u1")]}
main.apply_match_corrections(half)
check("KHU fixed the teams but not the score: our score still shows", (half["results"][0]["home_score"], half["results"][0]["away_score"]) == (2, 0), str(half["results"][0]["home_score"]))
lst = c.get("/api/admin/match-corrections/list", headers=H).json()
mine = next(x for x in lst["corrections"] if x["date"] == "2026-09-27")
check("and it is still marked as doing work (not 'KHU matches')", mine["applied_now"] and not mine["khu_matches"])
# KHU changes it to something unrelated: no guess is made
other = {"fixtures": [], "live": [], "results": [m("Rongo University", "rongo-university", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 3, 0, "u1")]}
main.apply_match_corrections(other)
check("a match that is neither the wrong version nor ours is left alone", other["results"][0]["home_team"] == "Rongo University")

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

print("9. The league table follows the correction (both teams move together)")
KEY = main.LEAGUES_BY_SHORT["NLM-SZ"]["key"]
def row(n, slug, p, w, d, l, gf, ga, pts, form):
    return {"team": n, "team_url": U + slug + "/", "team_logo_url": "logo-" + slug, "position": "0", "played": str(p), "won": str(w),
            "drawn": str(d), "lost": str(l), "goals_for": str(gf), "goals_against": str(ga), "goal_diff": str(gf - ga),
            "points": str(pts), "form": form}
import copy as _c
# KHU's table counts the matches the wrong way round: Falcons played all three, University only u3
khu_table = [row("Kisii Falcons", "kisii-falcons", 3, 2, 0, 1, 5, 3, 6, ["W", "L", "W"]),
             row("Bay Club", "bay-club", 1, 1, 0, 0, 2, 0, 3, ["W"]),
             row("Kisii University", "kisii-university", 1, 0, 0, 1, 1, 3, 0, ["L"]),
             row("Kabianga University", "kabianga-university", 1, 0, 0, 1, 0, 2, 0, ["L"])]
def load_table():
    main._pristine_standings[KEY] = _c.deepcopy(khu_table)
    main.cache["standings"][KEY] = {"short": "NLM-SZ", "standings": _c.deepcopy(khu_table)}
def table():
    return {r["team"]: r for r in main.cache["standings"][KEY]["standings"]}
for k in [x["corr_key"] for x in db.load_match_corrections()]: db.delete_match_correction(k)
load_table(); main.cache["fixtures_results"] = scraped(); main.apply_match_corrections(main.cache["fixtures_results"])
main.recompute_league_standings(KEY)
check("no corrections: the table is exactly KHU's", table()["Kisii Falcons"]["played"] == "3" and table()["Kisii University"]["played"] == "1")
for body in ({"league_short": "NLM-SZ", "date": "2026-09-27", "home_team": "Kisii Falcons", "away_team": "Kabianga University", "new_home_team": "Kisii University"},
             {"league_short": "NLM-SZ", "date": "2026-10-17", "home_team": "Kisii Falcons", "away_team": "Bay Club", "new_home_team": "Kisii University"}):
    r = c.post("/api/admin/match-corrections/set", headers=H, json=body)
    check("saved", r.status_code == 200 and "table" in r.json()["message"], r.text[:90])
t = table()
fal, uni, kab, bay = t["Kisii Falcons"], t["Kisii University"], t["Kabianga University"], t["Bay Club"]
check("Falcons lose the two matches (3 -> 1 played, 1 win, 3 points)",
      (fal["played"], fal["won"], fal["drawn"], fal["lost"], fal["goals_for"], fal["goals_against"], fal["goal_diff"], fal["points"]) == ("1", "1", "0", "0", "3", "1", "2", "3"), str(fal))
check("University gain them (1 -> 3 played: W 2-0, L 0-2, L 1-3; 3 points)",
      (uni["played"], uni["won"], uni["drawn"], uni["lost"], uni["goals_for"], uni["goals_against"], uni["goal_diff"], uni["points"]) == ("3", "1", "0", "2", "3", "5", "-2", "3"), str(uni))
check("the opponents' rows are untouched", kab["played"] == "1" and kab["points"] == "0" and bay["points"] == "3" and bay["goals_for"] == "2")
check("both teams' form follows their real results (oldest first)", uni["form"] == ["W", "L", "L"] and fal["form"] == ["W"], f"{uni['form']} {fal['form']}")
check("points still add up to wins and draws (3-1-0) on every row", all(int(r["points"]) == 3 * int(r["won"]) + int(r["drawn"]) for r in t.values()))
check("games played = W + D + L on every row", all(int(r["played"]) == int(r["won"]) + int(r["drawn"]) + int(r["lost"]) for r in t.values()))
check("positions are renumbered and the table is in order", [int(r["position"]) for r in main.cache["standings"][KEY]["standings"]] == [1, 2, 3, 4]
      and [r["team"] for r in main.cache["standings"][KEY]["standings"]][0] == "Kisii Falcons")
main.recompute_league_standings(KEY); main.recompute_league_standings(KEY)
check("recomputing again changes nothing (no double counting)", table()["Kisii University"]["played"] == "3" and table()["Kisii Falcons"]["played"] == "1")
# a later scrape rebuilds from KHU's wrong data and must give the same answer
main.cache["fixtures_results"] = scraped(); main.apply_match_corrections(main.cache["fixtures_results"]); load_table(); main.recompute_league_standings(KEY)
check("a fresh scrape of KHU's wrong data gives the same corrected table", table()["Kisii University"]["points"] == "3" and table()["Kisii Falcons"]["points"] == "3")
# KHU fixes its own page and table: the correction must stop moving the table
fixed_matches = {"fixtures": [], "live": [], "results": [
    m("Kisii University", "kisii-university", "Kabianga University", "kabianga-university", "27-09-2026 10:00", 2, 0, "u1"),
    m("Kisii University", "kisii-university", "Bay Club", "bay-club", "17-10-2026 11:00", 0, 2, "u2"),
    m("Kisii Falcons", "kisii-falcons", "Kisii University", "kisii-university", "18-10-2026 10:00", 3, 1, "u3")]}
main.apply_match_corrections(fixed_matches)
khu_table[0] = row("Kisii Falcons", "kisii-falcons", 1, 1, 0, 0, 3, 1, 3, ["W"])
khu_table[2] = row("Kisii University", "kisii-university", 3, 1, 0, 2, 3, 5, 3, ["W", "L", "L"])
load_table(); main.recompute_league_standings(KEY)
check("once KHU fixes its page the table is not adjusted again", table()["Kisii University"]["played"] == "3" and table()["Kisii Falcons"]["played"] == "1")

print("10. Opt out, hide, and the admin's own table numbers")
for k in [x["corr_key"] for x in db.load_match_corrections()]: db.delete_match_correction(k)
khu_table[0] = row("Kisii Falcons", "kisii-falcons", 3, 2, 0, 1, 5, 3, 6, ["W", "L", "W"])
khu_table[2] = row("Kisii University", "kisii-university", 1, 0, 0, 1, 1, 3, 0, ["L"])
main.cache["fixtures_results"] = scraped(); load_table()
c.post("/api/admin/match-corrections/set", headers=H, json={"league_short": "NLM-SZ", "date": "2026-09-27", "home_team": "Kisii Falcons",
       "away_team": "Kabianga University", "new_home_team": "Kisii University", "adjust_table": False})
check("with 'also fix the table' switched off the table is left alone",
      table()["Kisii Falcons"]["played"] == "3" and table()["Kisii University"]["played"] == "1")
check("but the match itself moved", any(x["match_url"] == "u1" and x["home_team"] == "Kisii University" for x in main.cache["fixtures_results"]["results"]))
for k in [x["corr_key"] for x in db.load_match_corrections()]: db.delete_match_correction(k)
main.cache["fixtures_results"] = scraped(); load_table()
c.post("/api/admin/match-corrections/set", headers=H, json={"league_short": "NLM-SZ", "date": "2026-10-18", "home_team": "Kisii Falcons",
       "away_team": "Kisii University", "hide": True})
check("hiding a match takes it out of BOTH teams' table rows",
      table()["Kisii Falcons"]["played"] == "2" and table()["Kisii University"]["played"] == "0" and table()["Kisii University"]["points"] == "0", str(table()["Kisii University"]))
db.save_team_stats("NLM-SZ", "Kisii Falcons", {"points": 99})
main.recompute_league_standings(KEY)
check("a number the admin set by hand still wins over everything", table()["Kisii Falcons"]["points"] == "99")
conn = db.get_connection(); conn.execute("DELETE FROM manual_team_stats_store") if hasattr(conn, "execute") else None; conn.commit(); conn.close()

print()
print("ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
