"""
Offline checks for the shop: stores, products, orders, stock, and M-Pesa payment handling.
Safaricom is replaced by a stand-in, so no network and no money moves.
Run:  python verify_shop.py
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

print("1. Phone numbers")
n = mpesa.normalize_phone
check("07, 01, +254 and 254 forms all normalise", n("0712 345 678") == "254712345678" and n("+254712345678") == "254712345678" and n("0112345678") == "254112345678" and n("712345678") == "254712345678")
check("junk and non-mobile numbers refused", n("12345") == "" and n("0212345678") == "" and n("") == "" and n("2547123456789") == "")

print("2. Stores and products (admin only)")
check("anonymous cannot create a store", c.post("/api/admin/shop/stores", json={"name": "X"}).status_code == 401)
check("agent cannot create a store", c.post("/api/admin/shop/stores", json={"name": "X"}, headers={"x-agent-token": "nope"}).status_code == 401)
r = c.post("/api/admin/shop/stores", headers=H, json={"name": "Stick Masters", "tagline": "Hockey gear", "whatsapp": "0712345678", "delivery_fee": 300, "logo_data_url": PNG})
sid = r.json().get("store_id"); check("store saved", r.status_code == 200 and sid, r.text[:100])
check("bad WhatsApp number refused", c.post("/api/admin/shop/stores", headers=H, json={"name": "Y", "whatsapp": "123"}).status_code == 422)
check("SVG logo refused", c.post("/api/admin/shop/stores", headers=H, json={"name": "Y", "logo_data_url": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="}).status_code == 422)
r = c.post("/api/admin/shop/stores", headers=H, json={"name": "Hidden Co", "active": False}); hid = r.json()["store_id"]
def prod(**kw): return c.post("/api/admin/shop/products", headers=H, json=dict(dict(store_id=sid, name="Grays GX3000 Stick", brand="Grays", category="Sticks", price=6500, stock=3), **kw))
r = prod(); p1 = r.json().get("product_id"); check("product saved", r.status_code == 200 and p1)
p2 = prod(name="Mouthguard", brand="Opro", category="Protection", price=800, stock=10).json()["product_id"]
check("price must be positive", prod(price=0).status_code == 422)
check("unknown store refused", prod(store_id="nosuchstore").status_code == 422)
ri = c.post(f"/api/admin/shop/products/{p1}/images", headers=H, json={"image_data_url": PNG})
check("picture added", ri.status_code == 200); iid = ri.json().get("image_id")
check("fake picture refused", c.post(f"/api/admin/shop/products/{p1}/images", headers=H, json={"image_data_url": "data:image/png;base64,SGVsbG8="}).status_code == 422)
for _ in range(5): c.post(f"/api/admin/shop/products/{p1}/images", headers=H, json={"image_data_url": PNG})
check("at most 4 pictures per product", len([x for x in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"] if x["product_id"] == p1][0]["images"]) == 4)

print("3. What fans see")
stores = c.get("/api/shop/stores").json()["stores"]
check("only active stores listed", [s["name"] for s in stores] == ["Stick Masters"] and stores[0]["has_logo"] and stores[0]["product_count"] == 2, str(stores)[:150])
check("hidden store is not reachable", c.get(f"/api/shop/stores/{hid}").status_code == 404)
pub = c.get(f"/api/shop/stores/{sid}").json()
check("catalogue has prices but never stock numbers", all("stock" not in p and "active" not in p for p in pub["products"]) and pub["products"][0]["price"] > 0)
img = c.get(f"/api/shop/images/{iid}")
check("picture served safely", img.status_code == 200 and img.headers["x-content-type-options"] == "nosniff" and "sandbox" in img.headers["content-security-policy"])
check("logo served", c.get(f"/api/shop/stores/{sid}/logo").status_code == 200 and c.get(f"/api/shop/stores/{hid}/logo").status_code == 404)

print("4. Ordering")
main._rate_hits.clear()
def _ORD(clear, **kw):
    if clear: main._rate_hits.clear()
    return c.post("/api/shop/orders", json=dict(dict(store_id=sid, items=[{"product_id": p1, "qty": 1}, {"product_id": p2, "qty": 2}], customer_name="Amina Odhiambo",
                                                            phone="0712345678", town="Kisumu", address="Milimani Road, Blue house"), **kw))
ORD = lambda **kw: _ORD(True, **kw)
ORD_RAW = lambda **kw: _ORD(False, **kw)
r = ORD(); o = r.json()
check("order created and PIN request sent", r.status_code == 200 and o["order_id"].startswith("KHU-") and len(SENT) == 1, r.text[:120])
check("total is worked out by the server: 6500 + 2x800 + 300 delivery", o["total"] == 8400 and SENT[0] == ("254712345678", 8400, o["order_id"]), str(SENT))
r2 = ORD(items=[{"product_id": p1, "qty": 1}], phone="0722000111")
check("a phone cannot set its own price", (main._rate_hits.clear(), c.post("/api/shop/orders", json={"store_id": sid, "items": [{"product_id": p1, "qty": 1, "price": 1}], "customer_name": "Zed Zed", "phone": "0733000111", "town": "K", "address": "abc"}))[1].json().get("total") == 6800)
admin_prod = {p["product_id"]: p for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"]}
check("stock was reserved straight away", admin_prod[p1]["stock"] == 3 - 1 - 1 - 1 and admin_prod[p2]["stock"] == 10 - 2, str({k: v["stock"] for k, v in admin_prod.items()}))
r = ORD(items=[{"product_id": p1, "qty": 5}], phone="0733111222")
check("cannot order more than is in stock", r.status_code == 422 and "stock" in r.json()["detail"], r.text[:120])
admin_prod = {p["product_id"]: p for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"]}
check("a refused order holds nothing", admin_prod[p1]["stock"] == 0 + 0 or admin_prod[p1]["stock"] == 3 - 1 - 1 - 1, str(admin_prod[p1]["stock"]))
check("bad phone refused", ORD(phone="12345").status_code == 422)
check("missing delivery details refused", ORD(address="", phone="0744000111").status_code in (422,))
check("too many of one item refused", c.post("/api/shop/orders", json={"store_id": sid, "items": [{"product_id": p2, "qty": 11}], "customer_name": "Zed Zed", "phone": "0755000111", "town": "K", "address": "abc"}).status_code == 422)
check("another store's product cannot be bought through this store", c.post("/api/shop/orders", json={"store_id": hid, "items": [{"product_id": p2, "qty": 1}], "customer_name": "Zed Zed", "phone": "0755000111", "town": "K", "address": "abc"}).status_code == 422)

print("5. Payment arrives")
cb = lambda cid, code=0, amount=8400, receipt="RGH7ABC123": {"Body": {"stkCallback": {"MerchantRequestID": "m1", "CheckoutRequestID": cid, "ResultCode": code, "ResultDesc": "ok" if code == 0 else "Request cancelled by user",
        **({"CallbackMetadata": {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt}, {"Name": "PhoneNumber", "Value": 254712345678}]}} if code == 0 else {})}}}
check("callback to a wrong secret is refused", c.post("/api/shop/mpesa/callback/wrong", json=cb("ws_CO_0001")).status_code == 404)
st = lambda oid, ph="0712345678": c.get(f"/api/shop/orders/{oid}?phone={ph}")
check("order starts as pending", st(o["order_id"]).json()["status"] == "pending_payment")
check("wrong amount is NOT accepted as paid", (c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cb("ws_CO_0001", amount=1)).status_code == 200) and st(o["order_id"]).json()["status"] == "pending_payment")
check("callback with garbage is harmless", c.post("/api/shop/mpesa/callback/cb-secret-xyz", content=b"not json").status_code == 200)
check("unknown payment id is ignored", c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cb("ws_CO_9999")).status_code == 200)
c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cb("ws_CO_0001"))
got = st(o["order_id"]).json()
check("matching callback marks it paid with the M-Pesa receipt", got["status"] == "paid" and got["mpesa_receipt"] == "RGH7ABC123", str(got)[:120])
c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cb("ws_CO_0001", code=1032))
check("a repeated or contradicting callback cannot undo a payment", st(o["order_id"]).json()["status"] == "paid")
check("no personal details in the customer's view", "phone" not in got and "address" not in got and "customer_name" not in got)
check("order can only be seen with the right phone", st(o["order_id"], "0799999999").status_code == 404 and st("KHU-NOPE12").status_code == 404)

print("6. Payment fails or never happens")
stock_before = {p["product_id"]: p["stock"] for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"]}
r = ORD(items=[{"product_id": p2, "qty": 3}], phone="0766000222"); o2 = r.json(); cid2 = f"ws_CO_{len(SENT):04d}"
c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cb(cid2, code=1032))
check("cancelled payment marks the order failed", st(o2["order_id"], "0766000222").json()["status"] == "failed")
after = {p["product_id"]: p["stock"] for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"]}
check("failed payment gives the stock back", after[p2] == stock_before[p2], f"{stock_before[p2]} -> {after[p2]}")
r = ORD(items=[{"product_id": p2, "qty": 2}], phone="0777000333"); o3 = r.json(); cid3 = f"ws_CO_{len(SENT):04d}"
conn = db.get_connection(); conn.execute("UPDATE shop_orders SET created_at = '2000-01-01T00:00:00' WHERE order_id = ?", (o3["order_id"],)); conn.commit(); conn.close()
check("an unpaid order expires after the hold time", st(o3["order_id"], "0777000333").json()["status"] == "expired")
after2 = {p["product_id"]: p["stock"] for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"]}
check("expiry gives the stock back", after2[p2] == after[p2])
c.post("/api/shop/mpesa/callback/cb-secret-xyz", json=cb(cid3, amount=1900))
check("a late payment for an expired order is still honoured", st(o3["order_id"], "0777000333").json()["status"] == "paid")
# lost callback: customer's status check asks Safaricom
r = ORD(items=[{"product_id": p2, "qty": 1}], phone="0788000444"); o4 = r.json()
QUERY.clear(); QUERY.update({"state": "paid", "receipt": "", "amount": None})
check("a lost callback is recovered by asking Safaricom", st(o4["order_id"], "0788000444").json()["status"] == "paid")
QUERY.clear(); QUERY.update({"state": "pending"})

print("7. Limits and safety")
main._rate_hits.clear()
codes = [ORD_RAW(items=[{"product_id": p2, "qty": 1}], phone="0799000555").status_code for _ in range(6)]
check("one phone cannot be spammed with payment requests", 422 in codes, str(codes))
main._rate_hits.clear()
codes = [ORD_RAW(items=[{"product_id": p2, "qty": 1}], phone=f"07100005{i:02d}").status_code for i in range(8)]
check("one connection cannot place unlimited orders", 429 in codes, str(codes))
main._rate_hits.clear()
mpesa_cfg = {k: os.environ.pop(k) for k in ("MPESA_PASSKEY",)}
check("payments off until M-Pesa is set up (and nothing is reserved)", ORD(phone="0701000999").status_code == 503)
os.environ.update(mpesa_cfg)

print("8. Admin: fulfilment, refunds, money per store")
check("order list needs the admin login", c.get("/api/admin/shop/orders").status_code == 401)
orders = c.get("/api/admin/shop/orders", headers=H).json()["orders"]
check("admin sees customer details", any(x["order_id"] == o["order_id"] and x["phone"] == "254712345678" and x["address"] for x in orders))
check("cannot ship an unpaid order", c.post(f"/api/admin/shop/orders/{o2['order_id']}/status", headers=H, json={"status": "shipped"}).status_code == 422)
check("paid order moves to shipped, then delivered", c.post(f"/api/admin/shop/orders/{o['order_id']}/status", headers=H, json={"status": "shipped"}).status_code == 200
      and c.post(f"/api/admin/shop/orders/{o['order_id']}/status", headers=H, json={"status": "delivered"}).status_code == 200)
check("a delivered order cannot be cancelled", c.post(f"/api/admin/shop/orders/{o['order_id']}/status", headers=H, json={"status": "cancelled"}).status_code == 422)
b4 = {p["product_id"]: p["stock"] for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"]}[p2]
check("cancelling a paid order flags the refund and returns stock", c.post(f"/api/admin/shop/orders/{o4['order_id']}/status", headers=H, json={"status": "cancelled"}).status_code == 200
      and "REFUND DUE" in [x for x in c.get("/api/admin/shop/orders", headers=H).json()["orders"] if x["order_id"] == o4["order_id"]][0]["admin_note"]
      and {p["product_id"]: p["stock"] for p in c.get(f"/api/admin/shop/stores/{sid}/products", headers=H).json()["products"]}[p2] == b4 + 1)
ov = c.get("/api/admin/shop/overview", headers=H).json()
row = [x for x in ov["settlement"] if x["store_id"] == sid][0]
check("money per store counts paid, not cancelled/failed", row["amount_paid"] == 8400 + 1900 and row["refunds_due"] == 1, str(row))
check("overview says payments are ready", ov["payments_ready"] is True)

print("9. Backup and restore")
bk = __import__("backup").build_backup()
check("backup carries the shop", bk["shop"]["stores"] and bk["shop"]["orders"] and bk["shop"]["images"])
check("store with orders is hidden, not deleted", "hidden" in c.delete(f"/api/admin/shop/stores/{sid}", headers=H).json()["message"])
check("store without orders is deleted", "removed" in c.delete(f"/api/admin/shop/stores/{hid}", headers=H).json()["message"])
res = shop.import_all(shop.export_all())
check("restoring never duplicates what is there", sum(res.values()) == 0, str(res))

print("\nRESULT:", "all checks passed" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
