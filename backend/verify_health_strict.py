"""
Offline checks for /api/health?strict=1 (the uptime-monitor mode). No network.
Run:  env -u DATABASE_URL python verify_health_strict.py
"""
import os, sys, tempfile, logging
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
if not os.environ.get("DATABASE_URL"):
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
import main
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)

db.init_db()
c = TestClient(main.app)
def ago(minutes): return (datetime.now() - timedelta(minutes=minutes)).isoformat()
def breaker(state): main.db.get_circuit_state = lambda: {"state": state, "consecutive_failures": 3 if state == "OPEN" else 0, "opened_at": None}

print("1. Plain call never changes")
breaker("CLOSED"); main.cache["last_refresh_success"] = ago(500)
r = c.get("/api/health")
check("plain call is 200 even when data is old", r.status_code == 200)
check("plain call has no strict fields", "healthy" not in r.json() and "problems" not in r.json())

print("2. Strict mode: healthy")
main.cache["last_refresh_success"] = ago(5)
r = c.get("/api/health?strict=1")
check("fresh data: 200", r.status_code == 200, r.text[:80])
check("healthy true, no problems", r.json()["healthy"] is True and r.json()["problems"] == [])
check("other spellings work (true/yes)", c.get("/api/health?strict=true").status_code == 200 and c.get("/api/health?strict=yes").status_code == 200)
check("strict=0 behaves like a plain call", "healthy" not in c.get("/api/health?strict=0").json())

print("3. Strict mode: stalled scraper")
main.cache["last_refresh_success"] = ago(main.HEALTH_MAX_AGE_MINUTES + 10)
r = c.get("/api/health?strict=1")
check("old data: 503", r.status_code == 503, str(r.status_code))
check("says how old", "minutes ago" in r.json()["problems"][0], r.json()["problems"][0])
check("not cached by anyone", r.headers.get("cache-control") == "no-store")
main.cache["last_refresh_success"] = ago(main.HEALTH_MAX_AGE_MINUTES - 5)
check("just inside the limit: still healthy", c.get("/api/health?strict=1").status_code == 200)

print("4. Circuit breaker open")
main.cache["last_refresh_success"] = ago(5); breaker("OPEN")
r = c.get("/api/health?strict=1")
check("open breaker: 503 even with fresh data", r.status_code == 503 and "circuit breaker" in r.json()["problems"][0])
main.cache["last_refresh_success"] = ago(main.HEALTH_MAX_AGE_MINUTES + 10)
check("both problems are listed", len(c.get("/api/health?strict=1").json()["problems"]) == 2)
breaker("CLOSED")

print("5. Just after a restart")
main.cache["last_refresh_success"] = None
main._PROCESS_STARTED = __import__("time").time() - 60
check("no refresh yet but server just started: healthy (no false alarm after a deploy)", c.get("/api/health?strict=1").status_code == 200)
main._PROCESS_STARTED = __import__("time").time() - 3600
r = c.get("/api/health?strict=1")
check("still no refresh an hour later: 503", r.status_code == 503 and "since this server started" in r.json()["problems"][0])

print("6. Junk input")
main.cache["last_refresh_success"] = "not-a-date"
check("unreadable timestamp does not crash", c.get("/api/health?strict=1").status_code in (200, 503))
check("junk strict value is ignored", c.get("/api/health?strict=%27%3Cscript%3E").status_code == 200)
check("limit is never tighter than two refresh cycles", main.HEALTH_MAX_AGE_MINUTES >= main.REFRESH_INTERVAL_MINUTES * 2)

print()
print("ALL CHECKS PASSED" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
