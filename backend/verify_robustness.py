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
import push as _push; _push.DB_PATH = db.DB_PATH; _push.init_push_table()

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
check("stages chronological: Group A first, Final last", d["stages"][0]=="Group A" and d["stages"][-1]=="Final", str(d["stages"]))
check("final not in group table", sum(r["played"] for r in tbl)==4)
check("list endpoint counts", c.get("/api/tournaments").json()["tournaments"][0]["matches_total"]==4)
check("league standings untouched", "premier_league_men" in main.cache["standings"] and len(main.cache["standings"]["premier_league_men"]["standings"])==1)
seedj=c.get("/api/admin/tournaments/export-seed", headers=H).json()
check("export has data", len(seedj["tournaments"])==1 and len(seedj["matches"])==4)
conn=db.get_connection(); conn.execute("DELETE FROM tournaments"); conn.execute("DELETE FROM tournament_matches"); conn.commit(); conn.close()
check("seed restore", db.import_tournaments_seed(seedj["tournaments"], seedj["matches"])==1 and len(db.load_tournament_matches(tid))==4)
check("delete tournament", c.delete(f"/api/admin/tournaments/{tid}", headers=H).status_code==200 and c.get(f"/api/tournaments/{tid}").status_code==404)

print("7. Match detail enrichment + top scorers")
murl="https://www.kenyahockeyunion.org/match/test-1/"
main.cache["fixtures_results"]={"results":[{"league":"Premier League Men","home_team":"Alpha","away_team":"Beta","home_score":2,"away_score":1,
    "match_url":murl,"date":"2026-10-01 10:00","state":"FT","home_logo_url":"https://www.kenyahockeyunion.org/a.png","away_logo_url":"",
    "scorers":[{"team":"home","player_name":"Ann Otieno","minute":12},{"team":"home","player_name":"Ann Otieno","minute":60},{"team":"away","player_name":"Bob Kamau","minute":30}],
    "cards":[{"team":"away","player_name":"Bob Kamau","card_type":"yellow","minute":44}]},
   {"league":"Premier League Men","home_team":"Beta","away_team":"Alpha","home_score":0,"away_score":1,"match_url":"","date":"2026-10-08 10:00","state":"FT",
    "scorers":[{"team":"away","player_name":"Ann Otieno","minute":5}],"cards":[]}],"fixtures":[],"live":[]}
main.scrape_match_detail=lambda u: {"date":"","matchday":"","venue":"","home_team":"Alpha","away_team":"Beta","home_score":None,"away_score":None,"is_live":False,"source_url":u}
md=c.get("/api/match",params={"url":murl}).json()
check("match detail has scorers/cards/league/state", len(md["scorers"])==3 and len(md["cards"])==1 and md["league"]=="Premier League Men" and md["state"]=="FT", str(md))
check("match detail falls back to cached score", md["home_score"]==2 and md["away_score"]==1)
check("match detail rejects off-site url", c.get("/api/match",params={"url":"https://evil.com/?kenyahockeyunion.org"}).status_code==400)
ts=c.get("/api/players/top-scorers").json()["players"]
check("top scorers derived + ordered", ts[0]["player_name"]=="Ann Otieno" and ts[0]["goals"]==3 and ts[1]["goals"]==1, str(ts))
check("top scorers league filter", len(c.get("/api/players/top-scorers",params={"league_short":"PLW"}).json()["players"])==0
      and len(c.get("/api/players/top-scorers",params={"league_short":"PLM"}).json()["players"])==2)
db.save_player_stats("PLM","Alpha","Ann Otieno",{"goals":7,"appearances":9,"yellow_cards":0,"red_cards":0,"green_cards":0})
ts=c.get("/api/players/top-scorers").json()["players"]
check("manual stat line wins over derived (no double count)", ts[0]["goals"]==7 and sum(1 for p in ts if p["player_name"]=="Ann Otieno")==1, str(ts))

print("8. Push validation, admin-only test push, refresh lock, EAT date filter")
sub={"endpoint":"https://fcm.googleapis.com/fcm/send/abc","keys":{"p256dh":"BHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg","auth":"YWFhYWFhYWFhYWFhYWFhYQ"}}
check("push subscribe accepts known push host", c.post("/api/push/subscribe",json=sub).status_code==200)
check("push subscribe rejects junk keys (list stuffing)", c.post("/api/push/subscribe",json=dict(sub,keys={"p256dh":"k","auth":"a"})).status_code==400)
bad=dict(sub,endpoint="http://169.254.169.254/latest")
check("push subscribe rejects internal/unknown host", c.post("/api/push/subscribe",json=bad).status_code==400)
bad2=dict(sub,endpoint="https://evil.com/?x=googleapis.com")
check("push subscribe rejects spoofed host", c.post("/api/push/subscribe",json=bad2).status_code==400)
check("push test needs admin token", c.post("/api/push/test").status_code in (401,403))
main._refresh_lock.acquire()
try:
    check("refresh_all_data skips when lock held", main.refresh_all_data(force=True) in (None, False))
finally:
    main._refresh_lock.release()
from datetime import datetime, timedelta, timezone
eat=datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
fx=[{"date":(eat+timedelta(hours=1)).strftime("%d-%m-%Y %H:%M")},{"date":(eat-timedelta(hours=5)).strftime("%d-%m-%Y %H:%M")},{"date":eat.strftime("%d-%m-%Y")}]
kept=main._filter_future_fixtures(fx)
check("EAT filter keeps upcoming + date-only today, drops past", len(kept)==2, str(len(kept)))

from pdf_fixtures import merge_pdf_fixtures_into_scraped
live=[{"league_short":"NLM-CZ","home_team":"Fire Flickers","away_team":"Dukes of Gloucester","date":"2026-10-24 12:00"}]
pdfm=[{"league_short":"NLM-CZ","home_team":"Fireflickers","away_team":"Dukes","date":"2026-10-24 13:00"},
      {"league_short":"NLM-CZ","home_team":"Dukes","away_team":"Chuka Uni","date":"2026-10-31 13:00"}]
mg=merge_pdf_fixtures_into_scraped(live,pdfm)
check("PDF names merge into live names (dedupe + canonical spelling)", len(mg)==2 and mg[1]["home_team"]=="Dukes of Gloucester", str(mg))

import scraper
st=[{"team":"Kisii Uni Ladies"}]
check("placeholder suppressed when live has 'Kisii Uni Ladies'", len(scraper.inject_placeholder_teams(list(st),"super_league_women"))==1)
check("placeholder still added when absent", len(scraper.inject_placeholder_teams([{"team":"Swans Hockey Club"}],"super_league_women"))==2)
import json as _json
_ts=_json.load(open(os.path.join(os.path.dirname(os.path.abspath(main.__file__)),"tournaments_seed.json")))
_ids=[m["match_id"] for m in _ts["matches"]]
check("tournaments_seed.json: unique ids, valid matches", len(_ids)==len(set(_ids)) and all(not main.tn.validate_match(m) for m in _ts["matches"]), str(len(_ids)))
_old={"id":"old-t","name":"Old"}; _om={"match_id":"old-m1","tournament_id":"old-t","home_team":"A","away_team":"B"}
db.import_tournaments_seed([_old],[_om])
db.import_tournaments_seed([],[],["old-t"])
check("retired tournament (no scores) is removed on re-seed", not any(t["id"]=="old-t" for t in db.load_tournaments()))
_om2=dict(_om,match_id="old-m2",tournament_id="old-t2",home_score=1,away_score=0)
db.import_tournaments_seed([{"id":"old-t2","name":"Old2"}],[_om2]); db.import_tournaments_seed([],[],["old-t2"])
check("retired tournament with scores is kept", any(t["id"]=="old-t2" for t in db.load_tournaments()))
_saved=main.cache.get("fixtures_results"); main.cache["fixtures_results"]=None
try:
    main.db.save_pdf_fixtures([{"league_short":"PLM","home_team":"A","away_team":"B","date":"2099-01-01 10:00","league":"Premier League Men","source":"pdf"}],"t.pdf")
    r=c.get("/api/fixtures")
    check("/api/fixtures falls back to saved PDF fixtures when live cache empty", r.status_code==200 and r.json()["is_stale"] is True and r.json()["total"]>=1, str(r.status_code))
finally:
    main.cache["fixtures_results"]=_saved

_b={"match_id":"u1","tournament_id":"ut","stage":"Men – Pool","group_name":"Men Pool","home_team":"Old A","away_team":"Old B","date":"2026-10-23 10:00","entered_by":"poster"}
db.import_tournaments_seed([{"id":"ut","name":"UT"}],[_b,dict(_b,match_id="u2"),dict(_b,match_id="u3")])
conn=db.get_connection(); conn.execute("UPDATE tournament_matches SET home_score=2, away_score=1, entered_by='Jo' WHERE match_id='u2'"); conn.execute("UPDATE tournament_matches SET home_team='Admin Fix', entered_by='Admin' WHERE match_id='u3'"); conn.commit(); conn.close()
db.import_tournaments_seed([],[dict(_b,home_team="New A",away_team="New B"),dict(_b,match_id="u2",home_team="New A",away_team="New B"),dict(_b,match_id="u3",home_team="New A",away_team="New B")])
_r={m["match_id"]:m for m in db.load_tournament_matches("ut")}
check("updated sheet refreshes an untouched fixture", _r["u1"]["home_team"]=="New A", str(_r["u1"]))
check("…but never overwrites a scored fixture", _r["u2"]["home_team"]=="Old A" and _r["u2"]["home_score"]==2)
check("…or an admin-edited fixture", _r["u3"]["home_team"]=="Admin Fix")
# Seed scores fill only untouched, unscored games
db.import_tournaments_seed([],[dict(_b,match_id="u1",home_team="New A",away_team="New B",home_score=3,away_score=1,entered_by="Results sheet"),
    dict(_b,match_id="u2",home_score=9,away_score=9,entered_by="Results sheet"),dict(_b,match_id="u3",home_score=9,away_score=9,entered_by="Results sheet")])
_r={m["match_id"]:m for m in db.load_tournament_matches("ut")}
check("seed score fills an unscored untouched fixture", _r["u1"]["home_score"]==3 and _r["u1"]["away_score"]==1 and _r["u1"]["entered_by"]=="Results sheet", str(_r["u1"]))
check("seed score never overwrites an agent score", _r["u2"]["home_score"]==2 and _r["u2"]["entered_by"]=="Jo", str(_r["u2"]))
check("seed score never overwrites an admin edit", _r["u3"]["home_score"] is None and _r["u3"]["entered_by"]=="Admin", str(_r["u3"]))
_k={"match_id":"u1","tournament_id":"ut","stage":"Men – Pool","group_name":"Men Pool","home_team":"New A","away_team":"New B","date":"2026-10-23 10:00","home_score":0,"away_score":0,"entered_by":"Results sheet"}
db.import_tournaments_seed([],[dict(_k,home_score=5)])
check("a re-import never changes an already-scored fixture", {m["match_id"]:m for m in db.load_tournament_matches("ut")}["u1"]["home_score"]==3)
# dbconn: SQLite→Postgres translation + sqlite3.Row-compatible rows
import dbconn as _dbc
_tr = _dbc.translate
check("translate: ? placeholders", _tr("SELECT 1 FROM t WHERE a = ? AND b = ?") == "SELECT 1 FROM t WHERE a = %s AND b = %s")
check("translate: INSERT OR IGNORE", _tr("INSERT OR IGNORE INTO t (a) VALUES (?)\n").endswith("ON CONFLICT DO NOTHING") and "OR IGNORE" not in _tr("INSERT OR IGNORE INTO t (a) VALUES (?)"))
check("translate: AUTOINCREMENT + CURRENT_TIMESTAMP", "SERIAL PRIMARY KEY" in _tr("id INTEGER PRIMARY KEY AUTOINCREMENT") and "now()::text" in _tr("c TEXT DEFAULT CURRENT_TIMESTAMP"))
check("translate: ADD COLUMN made idempotent", "ADD COLUMN IF NOT EXISTS" in _tr("ALTER TABLE t ADD COLUMN x TEXT"))
_r = _dbc.Row(["a", "b"], (1, "x"))
check("Row works like sqlite3.Row", _r["a"] == 1 and _r[1] == "x" and dict(_r) == {"a": 1, "b": "x"} and list(_r) == [1, "x"])
# Backup restore endpoint
_bk = {"agents": [], "results": [], "stats": [], "players": [],
       "tournaments": [{"id": "bk", "name": "Backup Cup", "status": "completed"}],
       "matches": [{"match_id": "bk1", "tournament_id": "bk", "stage": "Men – Final", "home_team": "A", "away_team": "B", "home_score": 2, "away_score": 1, "date": "2026-10-25 16:30", "entered_by": "Jo"}]}
r = c.post("/api/admin/restore", json=_bk)
check("restore needs the admin token", r.status_code == 401)
r = c.post("/api/admin/restore", headers=H, json=_bk)
_m = {m["match_id"]: m for m in db.load_tournament_matches("bk")}
check("restore brings back tournaments and scored matches", r.status_code == 200 and _m.get("bk1", {}).get("home_score") == 2 and _m["bk1"]["entered_by"] == "Jo", r.text[:200])
check("restore rejects non-JSON", c.post("/api/admin/restore", headers=H, content=b"not json").status_code == 400)
check("restore rejects a non-object file", c.post("/api/admin/restore", headers=H, json=[1, 2]).status_code == 400)
print("9. Same-named teams in different leagues stay separate")
_saved = (main.cache["standings"].copy(), main.cache["fixtures_results"])
main.cache["standings"].clear()
main.cache["standings"]["slw"] = {"short": "SLW", "standings": [{"team": "Gorillas", "team_url": "https://kenyahockeyunion.org/t/gor-w", "position": 2, "played": "3"}]}
main.cache["standings"]["nlm_ez"] = {"short": "NLM-EZ", "standings": [{"team": "Gorillas", "team_url": "https://kenyahockeyunion.org/t/gor-m", "position": 5, "played": "4"}]}
main.cache["fixtures_results"] = {"fixtures": [], "live": [], "results": [
    {"league_short": "SLW", "home_team": "Gorillas", "away_team": "Lady X", "home_team_url": "https://kenyahockeyunion.org/t/gor-w", "home_score": 2, "away_score": 0, "date": "2026-10-10"},
    {"league_short": "NLM-EZ", "home_team": "Gorillas", "away_team": "Men Y", "home_team_url": "", "home_score": 0, "away_score": 1, "date": "2026-10-11"},
]}
w = main.build_team_profile_from_cache("Gorillas", "", "SLW")
m = main.build_team_profile_from_cache("Gorillas", "", "NLM-EZ")
check("SLW Gorillas gets only SLW data", w["position"] == 2 and [r["opponent"] for r in w["recent_results"]] == ["Lady X"], str(w["recent_results"]))
check("NLM-EZ Gorillas gets only NLM-EZ data", m["position"] == 5 and [r["opponent"] for r in m["recent_results"]] == ["Men Y"], str(m["recent_results"]))
u = main.build_team_profile_from_cache("Gorillas", "https://kenyahockeyunion.org/t/gor-m")
check("URL alone pins the right league", u["league_short"] == "NLM-EZ" and [r["opponent"] for r in u["recent_results"]] == ["Men Y"])
main.cache["standings"].clear(); main.cache["standings"].update(_saved[0]); main.cache["fixtures_results"] = _saved[1]

print("10. Season snapshots are append-only; off-site backup")
main._rate_hits.clear()
main.cache["standings"]["t_plm"] = {"league": "Premier League Men", "short": "PLM", "standings": [{"team": "Z", "points": "9"}]}
r = c.post("/api/admin/seasons/snapshot?label=2099-test&title=Test", headers=H)
check("snapshot saved", r.status_code == 200, r.text[:120])
r = c.post("/api/admin/seasons/snapshot?label=2099-test", headers=H)
check("saving the same season again is refused", r.status_code == 409)
check("snapshot needs admin", c.post("/api/admin/seasons/snapshot?label=x1", headers={"x-admin-token": "bad"}).status_code == 401)
check("bad label rejected", c.post("/api/admin/seasons/snapshot?label=../x", headers=H).status_code in (400, 404, 422))
r = c.post("/api/admin/seasons/import", headers=H, json={"label": "2019-20", "title": "2019/20", "source": "KHU", "data": {"leagues": [], "results": []}})
check("past season imported", r.status_code == 200)
check("import cannot overwrite", c.post("/api/admin/seasons/import", headers=H, json={"label": "2019-20", "data": {}}).status_code == 409)
labels = [x["label"] for x in c.get("/api/seasons").json()["seasons"]]
check("seasons listed publicly", "2019-20" in labels and "2099-test" in labels)
check("season readable", c.get("/api/seasons/2019-20").json()["data"] == {"leagues": [], "results": []})
check("unknown season 404", c.get("/api/seasons/1900-01").status_code == 404)
import backup as _bk
b = _bk.build_backup()
check("backup includes seasons + restorable parts", {"agents", "results", "tournaments", "matches", "seasons"} <= set(b) and len(b["seasons"]) >= 2)
check("backup not configured by default", not _bk.is_configured() and c.post("/api/admin/backup/run", headers=H).status_code == 400)
sent = {}
class _FakeS3:
    def put_object(self, **kw): sent.update(kw)
import types, sys as _sys
_fake = types.SimpleNamespace(client=lambda *a, **k: _FakeS3())
_sys.modules["boto3"] = _fake
for k, v in dict(BACKUP_S3_ENDPOINT="https://x.example", BACKUP_S3_BUCKET="bkt", BACKUP_S3_KEY_ID="k", BACKUP_S3_SECRET="s").items():
    os.environ[k] = v
main._rate_hits.clear()
r = c.post("/api/admin/backup/run", headers=H)
check("backup uploads to a dated key", r.status_code == 200 and sent.get("Bucket") == "bkt" and sent["Key"].startswith("khu-backups/") and b"2019-20" in sent["Body"], r.text[:150])
check("status reports success", c.get("/api/admin/backup/status", headers=H).json()["ok"] is True)
for k in ("BACKUP_S3_ENDPOINT", "BACKUP_S3_BUCKET", "BACKUP_S3_KEY_ID", "BACKUP_S3_SECRET"):
    os.environ.pop(k, None)
_sys.modules.pop("boto3", None)
main.cache["standings"].pop("t_plm", None)

print("11. Match archive + match status")
main._rate_hits.clear()
_fx = {"league_short": "PLM", "league": "Premier League Men", "home_team": "Alpha", "away_team": "Beta", "date": "2026-10-03 15:00", "state": "NS", "home_score": None, "away_score": None}
_fx2 = {"league_short": "PLM", "league": "Premier League Men", "home_team": "Gamma", "away_team": "Delta", "date": "2999-01-01 15:00", "state": "NS", "home_score": None, "away_score": None}
_old_fr = main.cache["fixtures_results"]
main.cache["fixtures_results"] = {"fixtures": [_fx, _fx2], "results": [], "live": []}
main.archive_current_matches()
r = c.get("/api/matches/history?league=PLM&team=alph").json()
check("archive keeps a fixture and filters by team", r["total"] == 1 and r["matches"][0]["home_team"] == "Alpha", str(r)[:150])
# the match is played: result arrives, fixture disappears from the cache, archive keeps the score
_res = dict(_fx, state="FT", home_score=2, away_score=1)
main.cache["fixtures_results"] = {"fixtures": [_fx2], "results": [_res], "live": []}
main.archive_current_matches()
main.cache["fixtures_results"] = {"fixtures": [_fx2], "results": [], "live": []}   # later scrape forgets it
main.archive_current_matches()
a = c.get("/api/matches/history?team=alph").json()["matches"][0]
check("archived score survives a scrape that forgets the match", a["home_score"] == 2 and a["away_score"] == 1)
check("history filters by date and season", c.get("/api/matches/history?date_from=2026-10-01&date_to=2026-10-31").json()["total"] >= 1 and c.get("/api/matches/history?season=2026").json()["total"] >= 1)
_rs = c.get("/api/matches/history?kind=results").json()["matches"]
_fs = c.get("/api/matches/history?kind=fixtures").json()["matches"]
check("Results archive holds only played matches", _rs and all(m.get("home_score") is not None for m in _rs))
check("Fixtures archive holds only unplayed past dates", all(m.get("home_score") is None and m["date"][:10] < "2026-11-01" for m in _fs) and not any(m["home_team"] == "Gamma" for m in _fs))
check("bad kind rejected", c.get("/api/matches/history?kind=x").status_code == 422)
check("bad season rejected", c.get("/api/matches/history?season=abc").status_code == 422)
key = main._match_key(_fx2)
S = lambda **kw: c.post("/api/admin/matches/status", headers=H, json=dict(match_key=key, **kw))
check("status needs auth", c.post("/api/admin/matches/status", json={"match_key": key, "status": "postponed"}).status_code == 401)
check("unknown status refused", S(status="exploded").status_code == 422)
check("unknown match refused", c.post("/api/admin/matches/status", headers=H, json={"match_key": "X|a|b|2026-01-01", "status": "postponed"}).status_code == 404)
check("rescheduled needs a new date", S(status="rescheduled").status_code == 422)
# a PAST fixture marked postponed stays visible on Fixtures with its notice
main.cache["fixtures_results"] = {"fixtures": [_fx, _fx2], "results": [], "live": []}
k1 = main._match_key(_fx)
c.post("/api/admin/matches/status", headers=H, json={"match_key": k1, "status": "postponed", "reason": "Pitch waterlogged"})
fx = c.get("/api/fixtures").json()["fixtures"]
pin = [m for m in fx if m["home_team"] == "Alpha"]
check("past postponed match stays visible with its reason", pin and pin[0]["status_info"]["reason"] == "Pitch waterlogged")
c.delete(f"/api/admin/matches/status?match_key={k1}", headers=H)
main._status_changed()
check("clearing the notice removes it", not [m for m in c.get("/api/fixtures").json()["fixtures"] if m["home_team"] == "Alpha"])
# rescheduled shows at the new date
check("reschedule saved", S(status="rescheduled", new_date="2999-02-02 15:00", reason="Venue clash").status_code == 200)
fx = [m for m in c.get("/api/fixtures").json()["fixtures"] if m["home_team"] == "Gamma"][0]
check("rescheduled match moves to its new date", fx["date"] == "2999-02-02 15:00" and fx["original_date"] == "2999-01-01 15:00")
# abandoned live match leaves the live list
_lv = dict(_fx2, state="LIVE", home_score=1, away_score=0)
main.cache["fixtures_results"] = {"fixtures": [], "results": [], "live": [_lv]}
check("abandoned match with minute and score saved", S(status="abandoned", reason="Floodlight failure", minute=48, home_score=1, away_score=0).status_code == 200)
check("abandoned match is no longer 'live'", c.get("/api/live").json()["total"] == 0)
nt = c.get("/api/match-notices").json()["notices"]
check("public notices list it with the stop details", nt and nt[0]["status_info"]["minute"] == 48 and nt[0]["status_info"]["status"] == "abandoned")
import database as _d2
_cn = _d2.get_connection(); _n = _cn.execute("SELECT COUNT(*) FROM match_status_log").fetchone()[0]; _cn.close()
check("every change is logged", _n == 4, str(_n))
bk = __import__("backup").build_backup()
check("backup carries archive and statuses", len(bk["match_archive"]) >= 2 and key in bk["match_statuses"])
main.cache["fixtures_results"] = _old_fr

print("12. Analytics, sponsor slot, honours")
import insights as _ins
main._rate_hits.clear()
UA = {"user-agent": "TestBrowser/1.0"}
check("hit accepted (204)", c.post("/api/analytics/hit", json={"view": "home"}, headers=UA).status_code == 204)
c.post("/api/analytics/hit", json={"view": "home"}, headers=UA)
c.post("/api/analytics/hit", json={"view": "table"}, headers={"user-agent": "Other/2.0", "x-forwarded-for": "9.9.9.9"})
c.post("/api/analytics/hit", json={"view": "<script>"}, headers=UA)
c.post("/api/analytics/hit", json={"view": "fixtures"}, headers={**UA, "dnt": "1"})
c.post("/api/analytics/install", headers=UA)
sm = c.get("/api/admin/analytics/summary?days=7", headers=H).json()
check("views counted, unknown view and Do-Not-Track ignored", sm["views_by_page"].get("home") == 2 and sm["views_by_page"].get("table") == 1 and "fixtures" not in sm["views_by_page"] and len(sm["views_by_page"]) == 2, str(sm["views_by_page"]))
check("same browser counted once as a visitor, a different one separately", sm["total_visitor_days"] == 2, str(sm["total_visitor_days"]))
check("installs counted", sm["installs"] == 1)
check("analytics summary is admin-only", c.get("/api/admin/analytics/summary").status_code == 401)
check("no IP address stored", "9.9.9.9" not in str(_ins.export_all()) and all(len(r["vhash"]) == 20 for r in [dict(x) for x in __import__("database").get_connection().execute("SELECT vhash FROM analytics_seen").fetchall()]))
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
sp = lambda **kw: c.post("/api/admin/sponsors", headers=H, json=dict(dict(name="Acme", link_url="https://acme.example", tagline="Proud supporter", logo_data_url=PNG), **kw))
check("sponsor admin-only", c.post("/api/admin/sponsors", json={"name": "x", "link_url": "https://a.example"}).status_code == 401)
check("http link refused", sp(link_url="http://acme.example").status_code == 422)
check("link with embedded login refused", sp(link_url="https://user:pw@acme.example").status_code == 422)
check("javascript link refused", sp(link_url="javascript:alert(1)").status_code == 422)
check("SVG logo refused", sp(logo_data_url="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+").status_code == 422)
check("fake PNG label with non-image bytes refused", sp(logo_data_url="data:image/png;base64,SGVsbG8gd29ybGQ=").status_code == 422)
r = sp(); sid = r.json()["id"]
check("valid sponsor saved", r.status_code == 200 and sid)
check("sponsor shows publicly", [x["id"] for x in c.get("/api/sponsors/active").json()["sponsors"]] == [sid])
lg = c.get(f"/api/sponsors/{sid}/logo")
check("logo served as an image with nosniff", lg.status_code == 200 and lg.headers["content-type"] == "image/png" and lg.headers["x-content-type-options"] == "nosniff")
main._rate_hits.clear()
c.post(f"/api/sponsors/{sid}/impression", headers=UA); c.post(f"/api/sponsors/{sid}/impression", headers=UA); c.post(f"/api/sponsors/{sid}/click", headers=UA)
c.post("/api/sponsors/doesnotexist/click", headers=UA); c.post(f"/api/sponsors/{sid}/explode", headers=UA)
ad = [x for x in c.get("/api/admin/sponsors", headers=H).json()["sponsors"] if x["id"] == sid][0]
check("impressions and clicks counted for a live sponsor only", ad["impressions"] == 2 and ad["clicks"] == 1 and ad["click_rate"] == 50.0, str(ad))
check("public sponsor list hides link-less internals", set(c.get("/api/sponsors/active").json()["sponsors"][0]) == {"id", "name", "tagline", "link_url", "has_logo"})
sp(id=sid, active=False)
check("switched-off sponsor disappears", c.get("/api/sponsors/active").json()["sponsors"] == [])
c.post(f"/api/sponsors/{sid}/impression", headers=UA)
ad = [x for x in c.get("/api/admin/sponsors", headers=H).json()["sponsors"] if x["id"] == sid][0]
check("switched-off sponsor is not counted, logo kept on edit", ad["impressions"] == 2 and ad["has_logo"])
sp(id=sid, active=True, end_date="2000-01-01")
check("expired sponsor disappears", c.get("/api/sponsors/active").json()["sponsors"] == [])
bk2 = __import__("backup").build_backup()
check("backup carries sponsors and analytics", any(x["id"] == sid for x in bk2["sponsors"]) and bk2["analytics_daily"])
check("sponsor removable", c.delete(f"/api/admin/sponsors/{sid}", headers=H).status_code == 200 and c.delete(f"/api/admin/sponsors/{sid}", headers=H).status_code == 404)
import database as _dbh
_dbh.save_season_snapshot("2018-test", "2018 Test", {"leagues": [{"league": "Premier League Men", "short": "PLM", "standings": [{"position": "2", "team": "Second", "points": "30"}, {"position": "1", "team": "First FC", "points": "40"}]}]}, "test")
hon = [x for x in c.get("/api/history/honours").json()["seasons"] if x["label"] == "2018-test"][0]
check("roll of honour picks the team in position 1", hon["champions"] == [{"league": "Premier League Men", "short": "PLM", "champion": "First FC", "points": "40"}], str(hon))

print("13. Player profiles")
main._rate_hits.clear()
PNGP = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
_old_fr13 = main.cache["fixtures_results"]
_old_std13 = dict(main.cache["standings"])
main.cache["standings"]["t_plw"] = {"league": "Premier League Women", "short": "PLW", "standings": [{"team": "Lakers Hockey Club", "team_url": "https://kenyahockeyunion.org/t/lakers", "position": 1}]}
main.cache["fixtures_results"] = {"fixtures": [], "live": [], "results": [
    {"league": "Premier League Women", "league_short": "PLW", "home_team": "Lakers Hockey Club", "away_team": "Opp FC", "date": "2026-10-10 12:00",
     "state": "FT", "home_score": 2, "away_score": 0, "scorers": [{"team": "home", "player_name": "Amina Odhiambo", "minute": 12}, {"team": "home", "player_name": "Amina Odhiambo", "minute": 40}]}]}
PP = lambda **kw: c.post("/api/admin/players/profile", headers=H, json=dict(dict(league_short="PLW", team_name="Lakers Hockey Club", player_name="Amina Odhiambo",
        jersey=9, position="Forward", nationality="Kenyan", captain=True, bio="Club captain.", photo_data_url=PNGP), **kw))
check("profile needs a login", c.post("/api/admin/players/profile", json={"league_short": "PLW", "team_name": "x", "player_name": "y"}).status_code == 401)
check("unknown league refused", PP(league_short="XXX").status_code == 400)
check("bad position refused", PP(position="Wizard").status_code == 422)
check("shirt number over 99 refused", PP(jersey=100).status_code == 422)
check("SVG photo refused", PP(photo_data_url="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+").status_code == 422)
check("non-image bytes with an image label refused", PP(photo_data_url="data:image/png;base64,SGVsbG8gd29ybGQ=").status_code == 422)
check("oversized photo refused", PP(photo_data_url="data:image/png;base64," + "iVBORw0KGgo" + "A" * 410_000).status_code in (413, 422))
r = PP(); pid = r.json().get("player_id")
check("profile saved", r.status_code == 200 and pid and len(pid) == 12, r.text[:100])
pr = c.get(f"/api/players/{pid}").json()
check("player page has details, stats from recorded goals and goal log", pr["jersey"] == 9 and pr["position"] == "Forward" and pr["captain"] and pr["has_photo"]
      and pr["goals"] == 2 and sorted(g["minute"] for g in pr["goals_log"]) == [12, 40], str(pr)[:200])
check("player page links to the team", pr["team_url"] == "https://kenyahockeyunion.org/t/lakers")
ph = c.get(f"/api/players/{pid}/photo")
check("photo served as an image with nosniff and sandbox", ph.status_code == 200 and ph.headers["content-type"] == "image/png" and ph.headers["x-content-type-options"] == "nosniff" and "sandbox" in ph.headers["content-security-policy"])
check("bad player id is a 404, not an error", c.get("/api/players/zzzz").status_code == 404 and c.get("/api/players/" + "0" * 12).status_code == 404)
check("no personal details beyond the allowed fields", set(pr) <= {"player_id","league_short","team_name","player_name","jersey","position","nationality","captain","bio","has_photo","goals","appearances","yellow_cards","green_cards","red_cards","has_stat_line","league","team_url","team_logo_url","goals_log"}, str(sorted(pr)))
tp = c.get("/api/team?name=Lakers%20Hockey%20Club&league=PLW").json()
check("team profile lists the squad with the player", any(p["player_id"] == pid and p["jersey"] == 9 for p in tp.get("squad", [])), str(tp.get("squad"))[:200])
ts = c.get("/api/players/top-scorers?league_short=PLW").json()["players"]
check("top scorers rows link to player pages", ts and ts[0]["player_id"] == pid)
lst = c.get("/api/admin/players/list?league=PLW&team=Lakers%20Hockey%20Club", headers=H).json()["players"]
check("admin player list for a team", any(p["player_id"] == pid for p in lst))
check("player list needs a login", c.get("/api/admin/players/list?team=x").status_code == 401)
PP(remove_photo=True, photo_data_url="", jersey=10)
pr2 = c.get(f"/api/players/{pid}").json()
check("photo can be removed and details updated", not pr2["has_photo"] and pr2["jersey"] == 10 and c.get(f"/api/players/{pid}/photo").status_code == 404)
PP(photo_data_url=PNGP)
PP(jersey=11, photo_data_url="")
check("editing details keeps the existing photo", c.get(f"/api/players/{pid}").json()["has_photo"])
bkp = __import__("backup").build_backup()
check("backup carries profiles with photos", any(x["player_id"] == pid and x["photo_b64"] for x in bkp["player_profiles"]))
check("only an admin can delete a profile", c.delete(f"/api/admin/players/profile/{pid}").status_code == 401 and c.delete(f"/api/admin/players/profile/{pid}", headers=H).status_code == 200 and c.get(f"/api/players/{pid}").json()["goals"] == 2)
main.cache["fixtures_results"] = _old_fr13
main.cache["standings"].clear(); main.cache["standings"].update(_old_std13)

print("14. Squad import from the KHU website")
import khusquads, playerprofiles as _ppx
from bs4 import BeautifulSoup as _BS
SQUAD_HTML = """<div id="stab_main"><table id="jstable_plz"><thead><tr><th>Name</th><th></th><th>Shirt Number</th></tr></thead><tbody>
<tr><td><div class="jsDivLineEmbl"><a href="https://www.kenyahockeyunion.org/joomsport_player/ann-one/?sid=1"><img src="https://www.kenyahockeyunion.org/wp-content/uploads/player_st.png"></a>
 <div class="js_div_particName"><a href="x">Ann One</a></div></div></td><td>0</td><td>07</td></tr>
<tr><td><div class="js_div_particName">Bea Two</div></td><td>0</td><td></td></tr>
<tr><td><div class="js_div_particName">Cy Three</div><img src="/wp-content/uploads/cy-50x50.jpg"></td><td>1</td><td>101</td></tr>
</tbody></table></div>
<div class="jsplayerCart"><a href="/joomsport_player/ann-one/"><img src="/wp-content/uploads/ann-310x413.jpeg"></a><div class="js_div_particName">Ann One</div></div>
<div class="jsplayerCart"><a href="/joomsport_player/dee-four/"><img src="/wp-content/uploads/player_st.png"></a><div class="js_div_particName">Dee Four</div></div>"""
sq = khusquads.parse_squad(_BS(SQUAD_HTML, "lxml"), "https://www.kenyahockeyunion.org/t/x/")
by = {p["name"]: p for p in sq}
check("squad parsed: every name once, incl. card-only players", sorted(by) == ["Ann One", "Bea Two", "Cy Three", "Dee Four"], str(sorted(by)))
check("shirt numbers read (leading zero ok, blank = none, over 99 ignored)", by["Ann One"]["jersey"] == 7 and by["Bea Two"]["jersey"] is None and by["Cy Three"]["jersey"] is None)
check("big card photo wins, grey placeholder ignored", by["Ann One"]["photo_url"].endswith("ann-310x413.jpeg") and by["Dee Four"]["photo_url"] == "")
check("relative photo links resolved to KHU", by["Ann One"]["photo_url"].startswith("https://www.kenyahockeyunion.org/"))
JPEGB = b"\xff\xd8\xff\xe0" + b"0" * 50
tally = {"photos": 0, "photos_skipped": 0}
khusquads.import_team(_BS(SQUAD_HTML, "lxml"), "PLM", "Imp Team", "https://www.kenyahockeyunion.org/t/x/", lambda u: JPEGB, _ppx.add_from_source, tally)
check("import created the four players with one photo", tally.get("created") == 4 and tally["photos"] == 2, str(tally))
ann = [p for p in c.get("/api/admin/players/list?league=PLM&team=Imp Team", headers=H).json()["players"] if p["player_name"] == "Ann One"][0]
check("imported player has number and photo", ann["jersey"] == 7 and ann["has_photo"])
# an admin's own entries are never overwritten
_ppx.save_profile("PLM", "Imp Team", "Bea Two", 5, "Defender", "Kenyan", True, "Mine", "", False, "admin")
t2 = {"photos": 0, "photos_skipped": 0}
khusquads.import_team(_BS(SQUAD_HTML.replace("<td>0</td><td></td>", "<td>0</td><td>44</td>"), "lxml"), "PLM", "Imp Team", "https://www.kenyahockeyunion.org/t/x/", lambda u: JPEGB, _ppx.add_from_source, t2)
bea = [p for p in c.get("/api/admin/players/list?league=PLM&team=Imp Team", headers=H).json()["players"] if p["player_name"] == "Bea Two"][0]
check("existing profile keeps admin's number, position, bio", bea["jersey"] == 5 and bea["position"] == "Defender" and bea["bio"] == "Mine" and bea["captain"])
check("second run creates nothing new", t2.get("created", 0) == 0)
def _boom(u): raise RuntimeError("net down")
t3 = {"photos": 0, "photos_skipped": 0}
khusquads.import_team(_BS(SQUAD_HTML, "lxml"), "PLM", "Imp Team B", "https://www.kenyahockeyunion.org/t/x/", _boom, _ppx.add_from_source, t3)
check("a photo that fails to download does not stop the team", t3.get("created") == 4 and t3["photos_skipped"] >= 1, str(t3))
check("import needs the admin login", c.post("/api/admin/players/import-khu", json={}).status_code == 401 and c.get("/api/admin/players/import-khu/status").status_code == 401)
check("agent cannot start an import", c.post("/api/admin/players/import-khu", json={}, headers={"x-agent-token": "x"}).status_code == 401)
check("unknown league refused", c.post("/api/admin/players/import-khu", json={"league_short": "ZZZ"}, headers=H).status_code == 400)
main._rate_hits.clear()
main.cache["standings"]["t_imp"] = {"league": "Premier League Men", "short": "PLM", "standings": [{"team": "Imp Team", "team_url": "https://www.kenyahockeyunion.org/t/x/"}]}
import scraper as _scx
_orig_fp, _orig_pd = _scx.fetch_page, main.polite_delay
_scx.fetch_page = lambda u: _BS(SQUAD_HTML, "lxml"); main.polite_delay = lambda: None
main._fetch_khu_photo = lambda u: JPEGB
r = c.post("/api/admin/players/import-khu", json={"league_short": "PLM"}, headers=H)
st = c.get("/api/admin/players/import-khu/status", headers=H).json()
check("import runs and reports", r.status_code == 200 and st["running"] is False and st["teams_done"] >= 1 and st["teams_done"] == st["teams_total"] and st["failed_teams"] == [], str(st))
_scx.fetch_page, main.polite_delay = _orig_fp, _orig_pd
_ppx.save_profile("PLM", "Dup Team", "Barry", 14, "Forward", "", False, "", "", False, "agent")
_ppx.add_from_source("PLM", "Dup Team", "Danstone Barry", 14, JPEGB)
_dl = [p for p in c.get("/api/admin/players/list?league=PLM&team=Dup Team", headers=H).json()["players"]]
check("a shirt number identifies the player: import completes #14 instead of adding a second", len(_dl) == 1 and _dl[0]["player_name"] == "Barry" and _dl[0]["has_photo"] and _dl[0]["position"] == "Forward", str(_dl))
_ppx.add_from_source("PLM", "Dup Team", "Barry Otieno", 7, None)
check("a different shirt number is a different person", len(c.get("/api/admin/players/list?league=PLM&team=Dup Team", headers=H).json()["players"]) == 2)
PPX = lambda **kw: c.post("/api/admin/players/profile", headers=H, json=dict(dict(league_short="PLM", team_name="Dup Team", player_name="Someone Else", jersey=14), **kw))
r = PPX()
check("form refuses a second player with the same number in a team", r.status_code == 422 and "Barry" in r.json()["detail"] and "14" in r.json()["detail"], r.text[:160])
check("same number in another team is fine", c.post("/api/admin/players/profile", headers=H, json={"league_short": "PLM", "team_name": "Rival Hawks", "player_name": "Someone Else", "jersey": 14}).status_code == 200)
_bid = [p for p in c.get("/api/admin/players/list?league=PLM&team=Dup Team", headers=H).json()["players"] if p["player_name"] == "Barry"][0]["player_id"]
r = PPX(player_name="Danstone Barry", existing_id=_bid, position="Forward")
_after = c.get("/api/admin/players/list?league=PLM&team=Dup Team", headers=H).json()["players"]
_db = [p for p in _after if p["player_name"] == "Danstone Barry"]
check("renaming through the picked player keeps number, position and photo", r.status_code == 200 and len(_db) == 1 and _db[0]["jersey"] == 14 and _db[0]["has_photo"] and _db[0]["position"] == "Forward" and not [p for p in _after if p["player_name"] == "Barry"], str(_after)[:200])
# duplicates that already exist (made before the rule) are merged on request
_cn = __import__("database").get_connection()
_cn.execute("INSERT INTO player_profiles (player_id, league_short, team_name, player_name, jersey, position, updated_at) VALUES ('aaaaaaaaaaaa','PLM','Dup Team','Dan B',14,'','x')"); _cn.commit(); _cn.close()
check("merge needs the admin login", c.post("/api/admin/players/merge-duplicates").status_code == 401 and c.post("/api/admin/players/merge-duplicates", headers={"x-agent-token": "x"}).status_code == 401)
r = c.post("/api/admin/players/merge-duplicates", headers=H).json()
_fin = [p for p in c.get("/api/admin/players/list?league=PLM&team=Dup Team", headers=H).json()["players"] if p["jersey"] == 14]
check("existing duplicates merge into the fullest profile", len(r["merged"]) == 1 and len(_fin) == 1 and _fin[0]["player_name"] == "Danstone Barry" and _fin[0]["has_photo"], str([(p["player_name"], p["has_photo"], p["jersey"]) for p in _fin]))
check("merge with nothing to do says so", "No duplicates" in c.post("/api/admin/players/merge-duplicates", headers=H).json()["message"])
check("initials alone never match", _ppx._same_person("K.O", "Kevin Okoth") is False and _ppx._same_person("JB", "John Bosco") is False and _ppx._same_person("Ann One", "Ann One Two") is True)
check("photo downloads are limited to KHU's own host", __import__("scraper").is_allowed_khu_url("https://evil.example/x.jpg") is False)
main.cache["standings"].clear(); main.cache["standings"].update(_old_std13)


print("9. Same team, different spelling (Kisii Uni Men / Kisii University) — never merged with a different team")
B_ = "https://www.kenyahockeyunion.org/joomsport_team/"
_rows = [{"team": n, "team_url": B_ + n.lower().replace(" ", "-") + "/?sid=1", "team_logo_url": "L-" + n} for n in
         ["Kisii Falcons", "Kisii University", "Kabianga University", "Bay Club"]]
main.cache["standings"] = {"nlm_sz": {"league": "NLM-SZ", "short": "NLM-SZ", "standings": _rows}}
check("PDF spelling 'Kisii Uni Men' is the live 'Kisii University'", main._team_matches_fixture_side("Kisii University", "", "Kisii Uni Men", ""))
check("'Kisii Uni' and 'Kisii University Men' too", main._team_matches_fixture_side("Kisii University", "", "Kisii Uni", "") and main._team_matches_fixture_side("Kisii University", "", "Kisii University Men", ""))
check("Kisii Falcons is never Kisii University (any spelling)", not any(main._team_matches_fixture_side("Kisii Falcons", "", n, "") for n in ["Kisii University", "Kisii Uni Men", "Kisii Uni", "Kisii University Men"]))
check("the ladies' team is never the men's team", not main._team_matches_fixture_side("Kisii University", "", "Kisii Uni Ladies", ""))
check("a Dev squad is never the senior team", not main._team_matches_fixture_side("Western Jaguars", "", "Western Jaguars Dev", ""))
check("two different team links are never merged", not main._team_matches_fixture_side("Kisii University", B_ + "a/", "Kisii Uni Men", B_ + "b/"))
check("'Kisii Uni Men' resolves to the University standings row only", (main._find_standings_entry_for_team("Kisii Uni Men", "", "NLM-SZ") or {}).get("team") == "Kisii University")
check("and takes the University logo, not the Falcons one", main.fuzzy_match_logo("Kisii Uni Men", main.build_fuzzy_team_records()) == "L-Kisii University")

print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
