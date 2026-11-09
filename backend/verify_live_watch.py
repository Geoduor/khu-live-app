"""Live-watch pass: only today's teams are fetched; everything else carries over."""
import os, sys
os.environ.setdefault("KHU_LIVE_WATCH_MINUTES", "2")
import main
from datetime import datetime, timedelta
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n); fails += (not c)

today = (datetime.utcnow() + timedelta(hours=3)).strftime("%d-%m-%Y")
def M(h, a, st, hs=None, as_=None, d=today, lg="PLM"):
    return {"home_team": h, "away_team": a, "state": st, "home_score": hs, "away_score": as_, "date": d,
            "league_short": lg, "league": lg, "match_url": f"u/{h}/{a}/{d}", "home_team_url": "", "away_team_url": ""}
main.cache["fixtures_results"] = {
    "fixtures": [], "results": [M("Old A", "Old B", "FT", 1, 0, d="01-01-2026")],
    "live": [M("Alpha", "Beta", "LIVE", 0, 0)], "total_fixtures": 0, "total_results": 1, "total_live": 1}
main.cache["standings"] = {k: {"standings": [
    {"team": n, "team_url": f"http://x/{n}"} for n in ("Alpha", "Beta", "Old A", "Old B")]} for k in list(main.LEAGUES)[:1]}
check("only today's teams picked", main._teams_playing_today() == {"alpha", "beta"} or
      main._teams_playing_today() == {main._normalize_team_name("Alpha"), main._normalize_team_name("Beta")})
fetched = []
def fake(league_key, teams):
    fetched.extend(t["team"] for t in teams)
    return {"matches": [M("Alpha", "Beta", "LIVE", 1, 0)], "teams_fetched": len(teams), "teams_failed": 0, "incomplete": False}
main.scrape_league_results_via_teams = fake
main.db.save_fixtures_results = lambda *a, **k: None
main.archive_current_matches = lambda: None
main.db.load_pdf_fixtures = lambda: []
main.db.load_manual_results = lambda: []
main.db.should_attempt_scrape = lambda cooldown_seconds=300: True
ok = main.refresh_live_watch()
check("watch returned True", ok is True)
check("only Alpha/Beta fetched", sorted(fetched) == ["Alpha", "Beta"])
fr = main.cache["fixtures_results"]
check("live score updated to 1-0 once", [(m["home_score"], m["away_score"]) for m in fr["live"]] == [(1, 0)])
check("old result carried over", any(m["home_team"] == "Old A" for m in fr["results"]))
# no matches today -> no scrape
main.cache["fixtures_results"] = {"fixtures": [], "results": [M("Old A", "Old B", "FT", 1, 0, d="01-01-2026")], "live": []}
fetched.clear()
check("idle day does nothing", main.refresh_live_watch() is False and not fetched)
# breaker open -> skip
main.cache["fixtures_results"]["live"] = [M("Alpha", "Beta", "LIVE", 0, 0)]
main.db.should_attempt_scrape = lambda cooldown_seconds=300: False
check("breaker open skips", main.refresh_live_watch() is False and not fetched)
main.db.should_attempt_scrape = lambda cooldown_seconds=300: True
# lock held -> skip
main._refresh_lock.acquire()
check("full refresh running skips", main.refresh_live_watch() is False and not fetched)
main._refresh_lock.release()
print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
