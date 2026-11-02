"""Checks for the Cloudflare Worker support in the backend: only the Worker may reach the API once EDGE_KEY is set."""
import os, sys, tempfile, logging
os.environ.update(ADMIN_TOKEN="tok-123", EDGE_KEY="edge-key-abc", MPESA_CONSUMER_KEY="k", MPESA_CONSUMER_SECRET="s", MPESA_SHORTCODE="174379",
                  MPESA_PASSKEY="p", MPESA_CALLBACK_SECRET="cb", PUBLIC_API_URL="https://api.example.test", MPESA_CALLBACK_BASE="https://edge.example.test")
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
import main, mpesa
from fastapi.testclient import TestClient
fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)
db.init_db()
c = TestClient(main.app)
E = {"x-edge-key": "edge-key-abc"}
print("Edge lock")
check("direct call without the key is refused", c.get("/api/leagues").status_code == 403)
check("wrong key is refused", c.get("/api/leagues", headers={"x-edge-key": "nope"}).status_code == 403)
check("call through the Worker works", c.get("/api/leagues", headers=E).status_code == 200)
check("health check stays open", c.get("/api/health").status_code == 200)
check("Safaricom's secret-URL callback still works directly (fallback)", c.post("/api/shop/mpesa/callback/cb", json={}).status_code == 200)
check("a wrong callback secret is still refused", c.post("/api/shop/mpesa/callback/zzz", json={}).status_code == 404)
check("browser preflight (OPTIONS) is not blocked", c.options("/api/leagues", headers={"Origin": "https://khu-live-app.vercel.app", "Access-Control-Request-Method": "GET"}).status_code != 403)
check("callback address points at the Worker when set", mpesa.callback_url() == "https://edge.example.test/api/shop/mpesa/callback/cb", mpesa.callback_url())
print("Real visitor address")
main._rate_hits.clear()
codes = [c.get("/api/shop/stores", headers={**E, "x-edge-client-ip": "9.9.9.9"}).status_code for _ in range(125)]
check("limits count each visitor separately by the address the Worker reports", codes.count(429) >= 1 and c.get("/api/shop/stores", headers={**E, "x-edge-client-ip": "8.8.8.8"}).status_code == 200, str(codes.count(429)))
class R:  # a request that only claims to be the Worker
    headers = {"x-edge-key": "wrong", "x-edge-client-ip": "1.1.1.1", "x-forwarded-for": "5.5.5.5"}
    client = None
check("a forged visitor address is ignored without the key", main._client_ip(R) == "5.5.5.5")
class R2:
    headers = {"x-edge-key": "edge-key-abc", "x-edge-client-ip": "not an ip", "x-forwarded-for": "5.5.5.5"}
    client = None
check("a garbage visitor address falls back safely", main._client_ip(R2) == "5.5.5.5")
print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
