"""
Offline security checks (no network).  Run:  python verify_security.py
Covers the hardening from the security review: login lockout that can't be
spoofed, short-lived admin sessions, least-privilege agents, SSRF-safe
fetching, rate limits, size limits, docs/headers.
"""
import os, sys, tempfile, time, logging
os.environ["ADMIN_TOKEN"] = "tok-123-long-random"
os.environ["ADMIN_USERNAME"] = "boss"
os.environ["ADMIN_PASSWORD"] = "pw-pw-pw-pw-pw"
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
import main, scraper, push
from fastapi.testclient import TestClient

fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)

push.DB_PATH = db.DB_PATH
db.init_db(); push.init_push_table()
c = TestClient(main.app)
H = {"x-admin-token": "tok-123-long-random"}

print("1. Login lockout cannot be dodged with a fake X-Forwarded-For")
codes = []
for i in range(8):
    # attacker rotates the LEFT-most (client-controlled) entry; the proxy-appended one is constant
    r = c.post("/api/admin/login", json={"username": "boss", "password": f"wrong{i}"},
               headers={"x-forwarded-for": f"10.0.0.{i}, 203.0.113.9"})
    codes.append(r.status_code)
check("locked out after 5 wrong tries despite rotating spoofed IPs", codes[:5] == [401]*5 and codes[5:] == [429]*3, str(codes))
main._login_failures.clear()

print("2. Admin login hands out a short-lived session, never the master token")
r = c.post("/api/admin/login", json={"username": "boss", "password": "pw-pw-pw-pw-pw"})
tok = r.json().get("admin_token", "")
check("login ok", r.status_code == 200)
check("browser token is NOT the master token", tok != "tok-123-long-random" and tok.startswith("s1."))
check("session token works on admin endpoints", c.get("/api/admin/agents/list", headers={"x-admin-token": tok}).status_code == 200)
check("master token still works (curl/automation)", c.get("/api/admin/agents/list", headers=H).status_code == 200)
exp = int(time.time()) - 5
forged = f"s1.{exp}.{main._sign_admin_session(exp)}"
check("expired session rejected", c.get("/api/admin/agents/list", headers={"x-admin-token": forged}).status_code == 401)
check("tampered session rejected", c.get("/api/admin/agents/list", headers={"x-admin-token": tok[:-2] + "00"}).status_code == 401)
exp2 = int(time.time()) + 99999
check("forged expiry rejected", c.get("/api/admin/agents/list", headers={"x-admin-token": f"s1.{exp2}.{'0'*64}"}).status_code == 401)

print("3. Agents: strong passwords, per-account lockout, least privilege")
check("short agent password rejected", c.post("/api/admin/agents/create", headers=H, json={"username": "jo", "password": "short", "display_name": "Jo"}).status_code == 400)
check("agent created", c.post("/api/admin/agents/create", headers=H, json={"username": "jo", "password": "a-good-passphrase", "display_name": "Jo"}).status_code == 200)
row = [a for a in db.export_agents_raw() if a["username"] == "jo"][0]
check("new hash uses v2 (600k) salt", row["password_salt"].startswith("v2$"))
# legacy account upgrades on login
import hashlib
conn = db.get_connection(); legacy_salt = "ab" * 16
legacy_hash = hashlib.pbkdf2_hmac("sha256", b"old-password-1", legacy_salt.encode(), 100_000).hex()
conn.execute("INSERT INTO agents (username, display_name, password_hash, password_salt, active, created_at) VALUES ('old','Old',?,?,1,'2026-01-01')", (legacy_hash, legacy_salt)); conn.commit(); conn.close()
check("legacy agent can still log in", db.verify_agent_login("old", "old-password-1") == "Old")
check("…and is upgraded to v2", [a for a in db.export_agents_raw() if a["username"] == "old"][0]["password_salt"].startswith("v2$"))
check("…and still logs in afterwards", db.verify_agent_login("old", "old-password-1") == "Old")
atok = c.post("/api/agent/login", json={"username": "jo", "password": "a-good-passphrase"}).json()["token"]
AH = {"x-agent-token": atok}
check("agent can list results", c.get("/api/admin/results/list", headers=AH).status_code == 200)
check("agent CANNOT overwrite team standings", c.post("/api/admin/team-stats/set", headers=AH, json={"league_short": "PLM", "team_name": "X", "points": 99}).status_code == 401)
check("agent CANNOT edit player stats", c.post("/api/admin/player-stats/set", headers=AH, json={"league_short": "PLM", "team_name": "X", "player_name": "Y"}).status_code == 401)
check("agent CANNOT list agents / export seeds", c.get("/api/admin/agents/export-seed", headers=AH).status_code == 401)
main._login_failures.clear()
codes = [c.post("/api/agent/login", json={"username": "jo", "password": f"bad{i}"}, headers={"x-forwarded-for": f"1.1.1.{i}, 198.51.100.{i}"}).status_code for i in range(12)]
check("per-account lockout stops a botnet guessing one agent's password", 429 in codes, str(codes))
main._login_failures.clear()

print("4. Fetching is locked to KHU, redirects included (SSRF)")
check("look-alike host blocked", not main._is_khu_image_url("https://kenyahockeyunion.org.evil.com/x.png"))
check("userinfo trick blocked", not main._is_khu_image_url("https://kenyahockeyunion.org@evil.com/x.png"))
check("internal address blocked", not main._is_khu_image_url("http://169.254.169.254/latest/meta-data"))
class Resp:
    def __init__(s, code=200, headers=None, body=b"", ctype="image/png"):
        s.status_code = code; s.headers = dict(headers or {}); s.headers.setdefault("Content-Type", ctype); s._b = body
        s.is_redirect = code in (301, 302, 303, 307, 308)
    def raise_for_status(s): pass
    def iter_content(s, n): yield s._b
    def close(s): pass
class FakeSession:
    def __init__(s, responses): s.r = list(responses); s.urls = []
    def get(s, url, **kw): s.urls.append(url); return s.r.pop(0)
fs = FakeSession([Resp(302, {"Location": "http://169.254.169.254/latest/meta-data"})])
try:
    scraper.safe_get(fs, "https://kenyahockeyunion.org/a.png"); blocked = False
except Exception:
    blocked = True
check("redirect to an internal host is refused (and never requested)", blocked and fs.urls == ["https://kenyahockeyunion.org/a.png"], str(fs.urls))
fs = FakeSession([Resp(301, {"Location": "https://www.kenyahockeyunion.org/b.png"}), Resp(200, body=b"ok")])
check("same-site redirect still works", scraper.safe_get(fs, "https://kenyahockeyunion.org/a.png").status_code == 200)
main._KHU_SCRAPER = FakeSession([Resp(200, body=b"<svg onload=alert(1)>", ctype="image/svg+xml")])
check("SVG logo refused (can carry scripts)", c.get("/api/logo", params={"url": "https://kenyahockeyunion.org/x.svg"}).status_code == 415)
main._KHU_SCRAPER = FakeSession([Resp(200, body=b"x" * (3 * 1024 * 1024))])
check("oversized logo refused", c.get("/api/logo", params={"url": "https://kenyahockeyunion.org/big.png"}).status_code == 413)
main._KHU_SCRAPER = FakeSession([Resp(200, body=b"\x89PNG....")])
r = c.get("/api/logo", params={"url": "https://kenyahockeyunion.org/ok.png"})
check("good PNG served with nosniff + sandbox CSP", r.status_code == 200 and r.headers.get("x-content-type-options") == "nosniff" and "sandbox" in r.headers.get("content-security-policy", ""))

print("5. /api/match only fetches matches we already know")
main.cache["fixtures_results"] = {"results": [{"match_url": "https://kenyahockeyunion.org/match/known/"}], "fixtures": [], "live": []}
scraped = []
main.scrape_match_detail = lambda u: (scraped.append(u) or {"home_team": "A", "away_team": "B"})
check("unknown KHU page refused, nothing scraped", c.get("/api/match", params={"url": "https://kenyahockeyunion.org/wp-admin/"}).status_code == 404 and not scraped)
check("known match works", c.get("/api/match", params={"url": "https://kenyahockeyunion.org/match/known/"}).status_code == 200 and len(scraped) == 1)

print("6. Rate limits and size limits")
main._rate_hits.clear()
codes = [c.get("/api/team", params={"name": f"n{i}"}).status_code for i in range(70)]
check("/api/team throttled after 60/min", codes.count(429) >= 5, f"{codes.count(429)} blocked")
main._rate_hits.clear()
big = {"league_short": "PLM", "home_team": "A" * 500, "away_team": "B", "home_score": 1, "away_score": 0, "date": "2026-10-17 10:00"}
check("oversized team name rejected (422)", c.post("/api/admin/results/add", headers=H, json=big).status_code == 422)
check("absurd score rejected (422)", c.post("/api/admin/results/add", headers=H, json=dict(big, home_team="A", home_score=99999)).status_code == 422)
check("50 push favourites > cap rejected", c.post("/api/push/subscribe", json={"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "k", "auth": "a"}, "favoriteTeams": ["t"] * 61}).status_code == 422)
main._rate_hits.clear()
old = push.MAX_SUBSCRIPTIONS; push.MAX_SUBSCRIPTIONS = 1
sub = lambda n: {"endpoint": f"https://fcm.googleapis.com/fcm/send/{n}", "keys": {"p256dh": "k", "auth": "a"}}
c.post("/api/push/subscribe", json=sub("one"))
check("subscription table is capped", c.post("/api/push/subscribe", json=sub("two")).status_code == 503)
check("existing subscriber can still update", c.post("/api/push/subscribe", json=sub("one")).status_code == 200)
push.MAX_SUBSCRIPTIONS = old

print("7. Hardening defaults")
check("API docs hidden in production", c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404)
r = c.get("/api/leagues")
check("security headers present", r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("x-frame-options") == "DENY")
r = c.post("/api/admin/login", json={"username": "x", "password": "y"})
check("login responses are not cacheable", r.headers.get("cache-control") == "no-store")
r = c.options("/api/leagues", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
check("CORS never allows credentials", r.headers.get("access-control-allow-credentials") is None)

print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
