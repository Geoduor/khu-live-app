"""
Offline checks for security audit 5 (no network).  Run:  python verify_audit5.py
Covers: IPv6 address rotation, lockout counters that cannot be pushed out of memory, the image proxy no longer
fetching arbitrary KHU pages, real server-side agent logout, season-label newline, PDF error text.
"""
import os, sys, tempfile, logging, io
os.environ["ADMIN_TOKEN"] = "tok-123-long-random"
os.environ["ADMIN_USERNAME"] = "boss"
os.environ["ADMIN_PASSWORD"] = "pw-pw-pw-pw-pw"
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
import main, push
from fastapi import HTTPException
from fastapi.testclient import TestClient

fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)

push.DB_PATH = db.DB_PATH
db.init_db(); push.init_push_table()
c = TestClient(main.app)
H = {"x-admin-token": "tok-123-long-random"}

print("1. One IPv6 connection cannot dodge the lockout by rotating addresses")
main._login_failures.clear()
codes = []
for i in range(8):
    # same /64, different address every try (the proxy-appended, trusted entry is the right-most one)
    r = c.post("/api/admin/login", json={"username": "boss", "password": f"wrong{i}"},
               headers={"x-forwarded-for": f"2001:db8:1:2::{i + 1}"})
    codes.append(r.status_code)
check("locked after 5 tries across 8 addresses in one /64", codes[:5] == [401] * 5 and codes[5:] == [429] * 3, str(codes))
main._login_failures.clear()
r = c.post("/api/admin/login", json={"username": "boss", "password": "x"}, headers={"x-forwarded-for": "2001:db8:1:3::1"})
check("a different /64 is a different person", r.status_code == 401)
check("IPv4-mapped IPv6 counts as the IPv4 address", main._ip_bucket("::ffff:203.0.113.9") == "203.0.113.9")
check("IPv4 unchanged", main._ip_bucket("203.0.113.9") == "203.0.113.9")
check("two addresses in a /64 share one key", main._ip_bucket("2001:db8:1:2::1") == main._ip_bucket("2001:db8:1:2:aaaa::7"))
main._login_failures.clear()

print("2. The admin lockout counter cannot be pushed out of memory")
for i in range(35):
    main._login_record_failure(f"198.51.{i // 250}.{i % 250}", "admin:global")
check("admin is locked (35 failures recorded)", c.post("/api/admin/login", json={"username": "boss", "password": "pw-pw-pw-pw-pw"}).status_code == 429)
for i in range(main._LOGIN_MAX_KEYS + 500):   # an attacker flooding with fresh addresses
    main._login_record_failure(f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}")
check("admin counter survived the flood", "admin:global" in main._login_failures and len(main._login_failures["admin:global"]) >= 30)
check("table stays bounded", len(main._login_failures) <= main._LOGIN_MAX_KEYS)
check("admin still locked after the flood (correct password refused)", c.post("/api/admin/login", json={"username": "boss", "password": "pw-pw-pw-pw-pw"}).status_code == 429)
main._login_failures.clear()
main._login_check_allowed("192.0.2.77", "admin:global", 30)
check("merely checking an address does not add a table entry", "192.0.2.77" not in main._login_failures)
check("normal login works once the lock is cleared", c.post("/api/admin/login", json={"username": "boss", "password": "pw-pw-pw-pw-pw"}).status_code == 200)
main._login_failures.clear()

print("3. The image proxy only fetches images, never arbitrary KHU pages")
ok_urls = ["https://www.kenyahockeyunion.org/wp-content/uploads/2025/01/team.png", "https://kenyahockeyunion.org/wp-content/plugins/joomsport/img/default.png"]
bad_urls = ["https://www.kenyahockeyunion.org/", "https://www.kenyahockeyunion.org/?s=a", "https://www.kenyahockeyunion.org/joomsport_team/x/",
            "https://www.kenyahockeyunion.org/wp-admin/admin-ajax.php", "https://www.kenyahockeyunion.org/wp-json/wp/v2/users",
            "https://www.kenyahockeyunion.org/wp-content/../wp-login.php", "https://www.kenyahockeyunion.org/wp-content/%2e%2e/wp-login.php",
            "https://evil.example/wp-content/uploads/a.png", "https://kenyahockeyunion.org.evil.example/wp-content/uploads/a.png",
            "https://www.kenyahockeyunion.org/wp-content/uploads/" + "a" * 300]
check("real logo addresses accepted", all(main._is_khu_logo_url(u) for u in ok_urls))
check("pages, admin paths, feeds, traversal, look-alike hosts, long URLs refused", not any(main._is_khu_logo_url(u) for u in bad_urls),
      str([u for u in bad_urls if main._is_khu_logo_url(u)]))
check("endpoint refuses a KHU page", c.get("/api/logo", params={"url": bad_urls[0]}).status_code == 400)
calls = []
def boom(*a, **k):
    calls.append(1); raise main.requests.RequestException("down")
real_get = main.safe_get; main.safe_get = boom
main._LOGO_FAILED.clear(); main._LOGO_CACHE.clear()
u = "https://www.kenyahockeyunion.org/wp-content/uploads/missing.png"
codes = [c.get("/api/logo", params={"url": u}).status_code for _ in range(5)]
main.safe_get = real_get
check("a failing address reaches KHU once, not on every request", len(calls) == 1 and codes == [404] * 5, f"{len(calls)} fetches, {codes}")

print("4. Agent 'Log out' really ends the session")
check("agent created", c.post("/api/admin/agents/create", headers=H, json={"username": "jo", "password": "a-good-passphrase", "display_name": "Jo"}).status_code == 200)
tok = c.post("/api/agent/login", json={"username": "jo", "password": "a-good-passphrase"}).json()["token"]
A = {"x-agent-token": tok}
check("token works before logout", c.get("/api/admin/matches/search", headers=A).status_code == 200)
check("logout accepted", c.post("/api/agent/logout", headers=A).status_code == 204)
check("same token refused after logout", c.get("/api/admin/matches/search", headers=A).status_code == 401)
check("logout with a junk or missing token is harmless", c.post("/api/agent/logout", headers={"x-agent-token": "nope"}).status_code == 204 and c.post("/api/agent/logout").status_code == 204)
tok2 = c.post("/api/agent/login", json={"username": "jo", "password": "a-good-passphrase"}).json()["token"]
c.post("/api/agent/logout", headers={"x-agent-token": tok})
check("logging out one session leaves another untouched", c.get("/api/admin/matches/search", headers={"x-agent-token": tok2}).status_code == 200)

print("5. Smaller fixes")
for bad in ("2025-26\n", "2025-26\r\n", "2025 26"):
    try:
        main._season_label_or_400(bad); ok = False
    except HTTPException:
        ok = True
    check(f"season label {bad!r} refused", ok)
check("normal season label accepted", main._season_label_or_400("2025-26") == "2025-26")
r = c.post("/api/admin/fixtures/upload-pdf", headers=H, files={"file": ("x.pdf", io.BytesIO(b"%PDF-1.4 not really"), "application/pdf")})
check("broken PDF gets a plain message, no Python error text", r.status_code == 422 and "Error" not in r.text and "Exception" not in r.text and "Could not read that PDF" in r.text, r.text[:120])

print()
print("RESULT:", "all checks passed" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
