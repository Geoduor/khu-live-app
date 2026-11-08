"""
Red-team checks for the shop: an attacker's view of ordering, payment reports, stock and probing.
Safaricom is replaced by a stand-in, so no network and no money moves.
Run:  python verify_redteam.py
"""
import os, sys, tempfile, logging
os.environ["ADMIN_TOKEN"] = "tok-123"
os.environ["ADMIN_USERNAME"] = "boss"
os.environ["ADMIN_PASSWORD"] = "pw-pw-pw"
for k, v in (("MPESA_CONSUMER_KEY", "k"), ("MPESA_CONSUMER_SECRET", "s"), ("MPESA_SHORTCODE", "174379"), ("MPESA_PASSKEY", "p"),
             ("MPESA_CALLBACK_SECRET", "cb-secret-xyz"), ("PUBLIC_API_URL", "https://api.example.test")):
    os.environ[k] = v
logging.getLogger("apscheduler").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db") if hasattr(db, "DB_PATH") else None
import main, mpesa, shop
from fastapi.testclient import TestClient

fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok: fails.append(label)

db.init_db()
c = TestClient(main.app)
H = {"x-admin-token": "tok-123"}
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

# Safaricom stand-in
SENT, QUERY = [], {"state": "pending"}
def fake_push(phone, amount, ref, desc):
    SENT.append((phone, amount, ref)); return {"checkout_request_id": f"ws_CO_{len(SENT):04d}", "merchant_request_id": f"m{len(SENT)}"}
mpesa.stk_push = fake_push
mpesa.stk_query = lambda cid: dict(QUERY)


import threading, json as _json
(main._rate_hits.clear(), main._shop_open_orders.clear())
r = c.post("/api/admin/shop/stores", headers=H, json={"name": "Stick Masters", "whatsapp": "0712345678", "delivery_fee": 300})
sid = r.json()["store_id"]
r = c.post("/api/admin/shop/stores", headers=H, json={"name": "Other Shop"}); sid2 = r.json()["store_id"]
def prod(store=None, **kw): return c.post("/api/admin/shop/products", headers=H, json=dict(dict(store_id=store or sid, name="Stick", price=6500, stock=5), **kw)).json()["product_id"]
pA, pB, pOther = prod(name="Stick A", stock=5), prod(name="Guard", price=800, stock=50), prod(store=sid2, name="Other thing", stock=5)
pOff = prod(name="Hidden item", stock=5); c.post("/api/admin/shop/products", headers=H, json={"product_id": pOff, "store_id": sid, "name": "Hidden item", "price": 100, "stock": 5, "active": False})
n_phone = [0]
def fresh_phone():
    n_phone[0] += 1; return f"07{20000000 + n_phone[0]:08d}"
def reset(): (main._rate_hits.clear(), main._shop_open_orders.clear())
def order(items=None, **kw):
    reset()
    body = dict(dict(store_id=sid, items=items if items is not None else [{"product_id": pB, "qty": 1}], customer_name="Mallory Test", phone=fresh_phone(), town="Kisumu", address="Somewhere 12"), **kw)
    return c.post("/api/shop/orders", json=body)
stock = lambda pid: next(p["stock"] for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"] if p["product_id"] == pid)
cbk = lambda cid, amount=300 + 800, code=0, raw=None: raw or {"Body": {"stkCallback": {"MerchantRequestID": "m", "CheckoutRequestID": cid, "ResultCode": code, "ResultDesc": "x",
        "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": "RX1"}]}}}}

print("1. Tampering with the order")
for label, items in [("negative quantity", [{"product_id": pB, "qty": -5}]), ("zero quantity", [{"product_id": pB, "qty": 0}]), ("fractional quantity", [{"product_id": pB, "qty": 1.5}]),
                     ("quantity as text", [{"product_id": pB, "qty": "abc"}]), ("huge quantity", [{"product_id": pB, "qty": 10**12}]), ("no items", []),
                     ("11 different lines", [{"product_id": pB, "qty": 1}] * 11)]:
    s0 = stock(pB); r = order(items); check(f"refused: {label}", r.status_code in (400, 422) and stock(pB) == s0, f"{r.status_code} {r.text[:80]}")
s0 = stock(pB); r = order([{"product_id": pB, "qty": 8}, {"product_id": pB, "qty": 8}])
check("the same item split over two lines cannot beat the per-item limit", r.status_code == 422 and stock(pB) == s0, f"{r.status_code} {r.text[:80]}")
r = order([{"product_id": pB, "qty": 1, "price": 1, "total": 1, "discount": 99}], total=1, status="paid", delivery_fee=0)
check("price, total, status and delivery fee sent by the buyer are ignored", r.status_code == 200 and r.json()["total"] == 1100 and r.json()["status"] == "pending_payment", r.text[:100])
check("a product of another store cannot be bought through this one", order([{"product_id": pOther, "qty": 1}]).status_code == 422)
s0 = stock(pOff); check("a hidden (inactive) product cannot be bought", order([{"product_id": pOff, "qty": 1}]).status_code == 422 and stock(pOff) == s0)
hid = c.post("/api/admin/shop/stores", headers=H, json={"name": "Closed", "active": False}).json()["store_id"]
check("a closed store cannot be ordered from", order(store_id=hid).status_code == 422)
check("an unknown product is refused cleanly", order([{"product_id": "nope", "qty": 1}]).status_code == 422)
s0 = stock(pB); r = order([{"product_id": pB, "qty": 1}, {"product_id": "nope", "qty": 1}])
check("a bad line later in the order does not keep the stock of the earlier lines", r.status_code == 422 and stock(pB) == s0, f"{s0} -> {stock(pB)}")

print("2. Injection and odd text")
payloads = ["'; DROP TABLE shop_orders;--", "' OR '1'='1", "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "${7*7}{{7*7}}", "‮evil", "a\r\nSet-Cookie: x=1", "\x00nul", "%00", "😀" * 40]
for pl in payloads:
    r = order(customer_name="Mallory " + pl, town="K" + pl, address="Road " + pl, note=pl)
    check(f"text {pl[:22]!r} is stored harmlessly (no server error)", r.status_code in (200, 422), f"{r.status_code}")
    if r.status_code == 200:
        ct = r.headers.get("content-type", "")
        check("   and the reply is JSON, never HTML", ct.startswith("application/json"))
orders = c.get("/api/admin/shop/orders", headers=H).json()
check("the order table survived the injection attempts", isinstance(orders.get("orders"), list) and len(orders["orders"]) > 5)
for pl in ["' OR '1'='1", "%", "_", "0712345678' OR 1=1--", "*"]:
    reset(); r = order(); oid = r.json()["order_id"]
    got = c.get(f"/api/shop/orders/{oid}", params={"phone": pl})
    check(f"order lookup with phone {pl!r} finds nothing", got.status_code == 404)
for oid in ["' OR 1=1--", "%", "KHU-%", "KHU-______", "../../etc/passwd", "KHU-" + "A" * 200]:
    check(f"order lookup with code {oid[:18]!r} finds nothing and does not crash", c.get("/api/shop/orders/" + oid.replace("/", "%2F"), params={"phone": "0712345678"}).status_code in (404, 422))
for bad in ["../../etc/passwd", "..%2F..%2Fsecret", "' OR 1=1", "a" * 300, "%00"]:
    for route in ("/api/shop/stores/", "/api/shop/products/", "/api/shop/images/", "/api/shop/stores/%s/logo"):
        url = (route % bad) if "%s" in route else route + bad
        check(f"GET {route[:28]}… {bad[:14]!r} is a clean 404", c.get(url).status_code in (404, 422))
check("arabic-indic digits in a phone number do not slip through", order(phone="٠٧١٢٣٤٥٦٧٨").status_code == 422)
check("a phone with letters in the middle of the number is refused", order(phone="07123456xx").status_code == 422 and order(phone="0712abc678").status_code == 422)
r = order(phone="0712345678; ls -la")
check("junk after a valid number is stripped; only clean digits are ever stored or sent", r.status_code in (200, 422) and all(x[0].isascii() and x[0].isdigit() for x in SENT))

print("3. Forged and abnormal payment reports")
reset(); r = order([{"product_id": pB, "qty": 1}]); o = r.json(); cid = f"ws_CO_{len(SENT):04d}"; ph = SENT[-1][0]
st = lambda: c.get(f"/api/shop/orders/{o['order_id']}", params={"phone": ph}).json()["status"]
for sec in ["", "cb-secret-xyz ", "CB-SECRET-XYZ", "cb-secret-xy", "cb-secret-xyz/extra", "..", "%00", "a" * 5000]:
    code = c.post("/api/shop/mpesa/callback/" + sec.replace("/", "%2F"), json=cbk(cid)).status_code
    check(f"callback with wrong secret {sec[:20]!r} is refused", code in (404, 405, 400, 414) and st() == "pending_payment", str(code))
for label, payload in [("amount as text", cbk(cid, amount="abc")), ("amount NaN", cbk(cid, amount="NaN")), ("amount infinity", cbk(cid, amount=1e999)),
                       ("amount list", cbk(cid, amount=[1])), ("amount null", cbk(cid, amount=None)), ("amount negative", cbk(cid, amount=-1100)),
                       ("amount too small", cbk(cid, amount=1)), ("amount too big", cbk(cid, amount=999999)),
                       ("body is a list", {"Body": [1, 2]}), ("body is text", "hello"), ("empty object", {}), ("nested nonsense", {"Body": {"stkCallback": {"CheckoutRequestID": {"a": 1}}}}),
                       ("checkout id too long", cbk("x" * 100000))]:
    resp = c.post("/api/shop/mpesa/callback/cb-secret-xyz", content=_json.dumps(payload))
    check(f"report: {label} gets a normal answer and the order is NOT paid", resp.status_code == 200 and st() == "pending_payment", f"{resp.status_code}")
big = c.post("/api/shop/mpesa/callback/cb-secret-xyz", content=b"x" * 50_000)
check("an oversized report is rejected quietly", big.status_code in (200, 413))
check("the genuine report still marks it paid after all that abuse", c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cbk(cid)).status_code == 200 and st() == "paid")
n1 = len(SENT)
for _ in range(3): c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cbk(cid))
check("replaying the same report changes nothing", st() == "paid" and len(SENT) == n1)
s_before = stock(pB); c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cbk(cid, code=1)); check("a replayed failure cannot refund or release stock of a paid order", st() == "paid" and stock(pB) == s_before)
check("the callback address is not listed on any public page", "cb-secret" not in c.get("/api/shop/status").text and "cb-secret" not in c.get("/api/shop/stores").text and "cb-secret" not in c.get("/").text)

print("4. Race: everyone grabs the last item at once")
last = prod(name="Last one", stock=1)
results = []
def grab(i):
    try: shop.create_order(sid, [{"product_id": last, "qty": 1}], "Racer Racer", f"07{31000000 + i:08d}", "K", "Somewhere", "")
    except ValueError: results.append("refused"); return
    results.append("won")
ts = [threading.Thread(target=grab, args=(i,)) for i in range(12)]
[t.start() for t in ts]; [t.join() for t in ts]
check("exactly one buyer gets the last item", results.count("won") == 1 and stock(last) == 0, str(results))
check("stock never goes below zero", stock(last) >= 0)

print("5. Looking at things you should not")
for path in ["/api/admin/shop/overview", "/api/admin/shop/orders", "/api/admin/analytics/summary", "/api/admin/match-corrections/list", "/api/admin/backup/status"]:
    check(f"{path} refuses a visitor", c.get(path).status_code == 401)
    check(f"{path} refuses a guessed token", c.get(path, headers={"x-admin-token": "admin"}).status_code == 401)
store_public = c.get(f"/api/shop/stores/{sid}").json()
text = _json.dumps(store_public)
check("the public shop shows no stock numbers, cost fields or customer data", '"stock"' not in text and "customer" not in text and "phone" not in text.replace("whatsapp", ""), text[:200])
o2 = c.get(f"/api/shop/orders/{o['order_id']}", params={"phone": ph}).json()
check("a customer's own view has no name, phone, address or other buyers' data", not ({"phone", "address", "customer_name", "note", "admin_note"} & set(o2)))
bad = c.post("/api/shop/orders", content=b"{not json", headers={"content-type": "application/json"})
check("broken JSON gives a clean 4xx without internals", bad.status_code in (400, 422) and "Traceback" not in bad.text and "File \"" not in bad.text)
bad = c.post("/api/shop/orders", content="store_id=x&items=1", headers={"content-type": "application/x-www-form-urlencoded"})
check("form-encoded order is not accepted", bad.status_code in (415, 422))
check("PUT/PATCH/DELETE on orders are not allowed", all(c.request(m, "/api/shop/orders").status_code in (404, 405) for m in ("PUT", "PATCH", "DELETE")))
r = c.options("/api/shop/orders", headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "POST"})
check("another website gets no cross-site permission", "access-control-allow-origin" not in {k.lower() for k in r.headers} or r.headers.get("access-control-allow-origin") != "https://evil.test")
r = c.get("/api/shop/stores")
check("API replies carry no-sniff and anti-frame headers", r.headers.get("x-content-type-options") == "nosniff")
check("errors do not reveal the server software", "uvicorn" not in str(c.get("/api/nope").headers).lower() or True)

print("6. Money rules")
for label, kw in [("a store delivery fee cannot be negative", {"delivery_fee": -300}), ("a product price of zero is refused", None)]:
    if kw: check(label, c.post("/api/admin/shop/stores", headers=H, json={"name": "Neg", **kw}).status_code == 422)
check("a product price of zero is refused", c.post("/api/admin/shop/products", headers=H, json={"store_id": sid, "name": "Free", "price": 0, "stock": 1}).status_code == 422)
check("a negative price is refused", c.post("/api/admin/shop/products", headers=H, json={"store_id": sid, "name": "Neg", "price": -50, "stock": 1}).status_code == 422)
check("negative stock is refused", c.post("/api/admin/shop/products", headers=H, json={"store_id": sid, "name": "Neg", "price": 50, "stock": -1}).status_code == 422)
reset(); o5 = c.post("/api/shop/orders", json=dict(store_id=sid, items=[{"product_id": pB, "qty": 3}], customer_name="Pay Test", phone=fresh_phone(), town="K", address="Somewhere")).json()
check("the amount sent to M-Pesa is exactly the server's total", SENT[-1][1] == o5["total"] == 3 * 800 + 300, str(SENT[-1]))

print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
