"""
shop.py — stores, products and orders for the in-app shop.

Rules that keep money and stock honest:
  * Prices and totals are ALWAYS worked out here from the saved product prices; whatever a phone sends is ignored.
  * Stock is reserved the moment an order is created (one atomic UPDATE per product), and given back if the
    payment fails, expires (15 minutes) or the order is cancelled before it ships.
  * An order is only ever marked paid by (a) Safaricom's callback to a secret URL whose amount matches, or
    (b) a status query we ourselves send to Safaricom. Never by the customer's phone.
Personal data kept per order: name, phone, town, address, optional note. Nothing else about the customer.
"""
import json
import re
import secrets
import threading
from datetime import datetime, timedelta

import database as db
import playerprofiles as _pp

ORDER_HOLD_MINUTES = 15
MAX_LINES, MAX_QTY, MAX_IMAGES = 10, 10, 4
STATUSES = ("pending_payment", "paid", "processing", "shipped", "delivered", "failed", "expired", "cancelled")
ADMIN_STEPS = {"processing": ("paid", "processing"), "shipped": ("paid", "processing"),
               "delivered": ("shipped", "processing", "paid"), "cancelled": ("paid", "processing", "shipped")}
_ready = False
_lock = threading.Lock()
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _ensure(conn):
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        conn.execute("""CREATE TABLE IF NOT EXISTS shop_stores (
            store_id TEXT PRIMARY KEY, name TEXT NOT NULL, tagline TEXT DEFAULT '', whatsapp TEXT DEFAULT '',
            delivery_fee INTEGER DEFAULT 0, delivery_note TEXT DEFAULT '', active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0,
            logo_mime TEXT DEFAULT '', logo_b64 TEXT DEFAULT '', created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS shop_products (
            product_id TEXT PRIMARY KEY, store_id TEXT NOT NULL, name TEXT NOT NULL, brand TEXT DEFAULT '', category TEXT DEFAULT '',
            description TEXT DEFAULT '', price INTEGER NOT NULL, stock INTEGER NOT NULL DEFAULT 0, active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS shop_images (
            image_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, position INTEGER DEFAULT 0, mime TEXT NOT NULL, b64 TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS shop_orders (
            order_id TEXT PRIMARY KEY, store_id TEXT NOT NULL, store_name TEXT DEFAULT '', customer_name TEXT NOT NULL, phone TEXT NOT NULL,
            town TEXT DEFAULT '', address TEXT DEFAULT '', note TEXT DEFAULT '', items_json TEXT NOT NULL,
            subtotal INTEGER NOT NULL, delivery_fee INTEGER NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL,
            checkout_request_id TEXT DEFAULT '', merchant_request_id TEXT DEFAULT '', mpesa_receipt TEXT DEFAULT '',
            failure_reason TEXT DEFAULT '', admin_note TEXT DEFAULT '', stock_held INTEGER DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.commit()
        _ready = True


def _now() -> str:
    return datetime.now().isoformat()


def _clean(s, n) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", " ".join(str(s or "").split()))[:n]


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass


# ───────────────────────── stores ─────────────────────────
def save_store(store_id, name, tagline, whatsapp, delivery_fee, delivery_note, active, sort, logo_data_url="", remove_logo=False) -> str:
    name = _clean(name, 60)
    if not name:
        raise ValueError("Give the store a name.")
    fee = int(delivery_fee or 0)
    if not 0 <= fee <= 20000:
        raise ValueError("Delivery fee must be between 0 and 20,000 KES.")
    wa = re.sub(r"[^0-9]", "", whatsapp or "")
    if wa and not re.fullmatch(r"254[17][0-9]{8}", re.sub(r"^0", "254", wa)):
        raise ValueError("The WhatsApp number must be a Kenyan mobile, e.g. 0712345678.")
    wa = re.sub(r"^0", "254", wa)
    conn = db.get_connection()
    try:
        _ensure(conn)
        old = conn.execute("SELECT logo_mime, logo_b64 FROM shop_stores WHERE store_id = ?", (store_id,)).fetchone() if store_id else None
        if logo_data_url:
            mime, b64 = _pp.decode_photo(logo_data_url)
        elif old and not remove_logo:
            mime, b64 = old["logo_mime"], old["logo_b64"]
        else:
            mime, b64 = "", ""
        if old:
            conn.execute("""UPDATE shop_stores SET name=?, tagline=?, whatsapp=?, delivery_fee=?, delivery_note=?, active=?, sort=?,
                            logo_mime=?, logo_b64=? WHERE store_id=?""",
                         (name, _clean(tagline, 120), wa, fee, _clean(delivery_note, 200), 1 if active else 0, int(sort or 0), mime, b64, store_id))
        else:
            store_id = secrets.token_hex(5)
            conn.execute("""INSERT INTO shop_stores (store_id, name, tagline, whatsapp, delivery_fee, delivery_note, active, sort,
                            logo_mime, logo_b64, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (store_id, name, _clean(tagline, 120), wa, fee, _clean(delivery_note, 200), 1 if active else 0, int(sort or 0), mime, b64, _now()))
        conn.commit()
        return store_id
    finally:
        conn.close()


def delete_store(store_id: str) -> str:
    """Remove a store with no orders; a store that has orders is only hidden, so records stay complete."""
    conn = db.get_connection()
    try:
        _ensure(conn)
        if not conn.execute("SELECT 1 FROM shop_stores WHERE store_id = ?", (store_id,)).fetchone():
            return "missing"
        if conn.execute("SELECT 1 FROM shop_orders WHERE store_id = ?", (store_id,)).fetchone():
            conn.execute("UPDATE shop_stores SET active = 0 WHERE store_id = ?", (store_id,))
            conn.commit()
            return "hidden"
        for r in conn.execute("SELECT product_id FROM shop_products WHERE store_id = ?", (store_id,)).fetchall():
            conn.execute("DELETE FROM shop_images WHERE product_id = ?", (r["product_id"],))
        conn.execute("DELETE FROM shop_products WHERE store_id = ?", (store_id,))
        conn.execute("DELETE FROM shop_stores WHERE store_id = ?", (store_id,))
        conn.commit()
        return "deleted"
    finally:
        conn.close()


def _store_public(r, admin=False) -> dict:
    d = {"store_id": r["store_id"], "name": r["name"], "tagline": r["tagline"] or "", "delivery_fee": r["delivery_fee"] or 0,
         "delivery_note": r["delivery_note"] or "", "has_logo": bool(r["logo_b64"]), "whatsapp": r["whatsapp"] or ""}
    if admin:
        d.update({"active": bool(r["active"]), "sort": r["sort"] or 0})
    return d


def list_stores(admin=False) -> list:
    conn = db.get_connection()
    try:
        _ensure(conn)
        q = "SELECT * FROM shop_stores" + ("" if admin else " WHERE active = 1") + " ORDER BY sort, name"
        out = []
        for r in conn.execute(q).fetchall():
            d = _store_public(r, admin)
            d["product_count"] = conn.execute("SELECT COUNT(*) AS n FROM shop_products WHERE store_id = ?" + ("" if admin else " AND active = 1"),
                                              (r["store_id"],)).fetchone()["n"]
            out.append(d)
        return out
    finally:
        conn.close()


def get_store(store_id: str, admin=False):
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("SELECT * FROM shop_stores WHERE store_id = ?" + ("" if admin else " AND active = 1"), (store_id,)).fetchone()
        return _store_public(r, admin) if r else None
    finally:
        conn.close()


def get_store_logo(store_id: str):
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("SELECT logo_mime, logo_b64 FROM shop_stores WHERE store_id = ? AND active = 1", (store_id,)).fetchone()
    finally:
        conn.close()
    if not r or not r["logo_b64"]:
        return None
    import base64
    return r["logo_mime"], base64.b64decode(r["logo_b64"])


# ───────────────────────── products ─────────────────────────
def save_product(product_id, store_id, name, brand, category, description, price, stock, active) -> str:
    name = _clean(name, 100)
    if not name:
        raise ValueError("Give the product a name.")
    price, stock = int(price), int(stock)
    if not 1 <= price <= 1_000_000:
        raise ValueError("Price must be between 1 and 1,000,000 KES.")
    if not 0 <= stock <= 100_000:
        raise ValueError("Stock must be between 0 and 100,000.")
    conn = db.get_connection()
    try:
        _ensure(conn)
        if not conn.execute("SELECT 1 FROM shop_stores WHERE store_id = ?", (store_id,)).fetchone():
            raise ValueError("Choose the store this product belongs to.")
        now = _now()
        if product_id and conn.execute("SELECT 1 FROM shop_products WHERE product_id = ?", (product_id,)).fetchone():
            conn.execute("""UPDATE shop_products SET store_id=?, name=?, brand=?, category=?, description=?, price=?, stock=?, active=?, updated_at=?
                            WHERE product_id=?""", (store_id, name, _clean(brand, 40), _clean(category, 40), _clean(description, 600),
                                                    price, stock, 1 if active else 0, now, product_id))
        else:
            product_id = secrets.token_hex(5)
            conn.execute("""INSERT INTO shop_products (product_id, store_id, name, brand, category, description, price, stock, active, created_at, updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (product_id, store_id, name, _clean(brand, 40), _clean(category, 40),
                                                                _clean(description, 600), price, stock, 1 if active else 0, now, now))
        conn.commit()
        return product_id
    finally:
        conn.close()


def delete_product(product_id: str) -> bool:
    conn = db.get_connection()
    try:
        _ensure(conn)
        conn.execute("DELETE FROM shop_images WHERE product_id = ?", (product_id,))
        cur = conn.execute("DELETE FROM shop_products WHERE product_id = ?", (product_id,))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def add_image(product_id: str, data_url: str) -> str:
    mime, b64 = _pp.decode_photo(data_url)
    conn = db.get_connection()
    try:
        _ensure(conn)
        if not conn.execute("SELECT 1 FROM shop_products WHERE product_id = ?", (product_id,)).fetchone():
            raise ValueError("Save the product first, then add pictures.")
        n = conn.execute("SELECT COUNT(*) AS n FROM shop_images WHERE product_id = ?", (product_id,)).fetchone()["n"]
        if n >= MAX_IMAGES:
            raise ValueError(f"A product can have at most {MAX_IMAGES} pictures.")
        iid = secrets.token_hex(6)
        conn.execute("INSERT INTO shop_images (image_id, product_id, position, mime, b64) VALUES (?,?,?,?,?)", (iid, product_id, n, mime, b64))
        conn.commit()
        return iid
    finally:
        conn.close()


def delete_image(image_id: str) -> bool:
    conn = db.get_connection()
    try:
        _ensure(conn)
        cur = conn.execute("DELETE FROM shop_images WHERE image_id = ?", (image_id,))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def get_image(image_id: str):
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("""SELECT i.mime, i.b64 FROM shop_images i JOIN shop_products p ON p.product_id = i.product_id
                            JOIN shop_stores s ON s.store_id = p.store_id WHERE i.image_id = ? AND p.active = 1 AND s.active = 1""", (image_id,)).fetchone()
    finally:
        conn.close()
    if not r:
        return None
    import base64
    return r["mime"], base64.b64decode(r["b64"])


def _product_public(conn, r, admin=False) -> dict:
    imgs = [x["image_id"] for x in conn.execute("SELECT image_id FROM shop_images WHERE product_id = ? ORDER BY position", (r["product_id"],)).fetchall()]
    d = {"product_id": r["product_id"], "store_id": r["store_id"], "name": r["name"], "brand": r["brand"] or "", "category": r["category"] or "",
         "description": r["description"] or "", "price": r["price"], "in_stock": r["stock"] > 0, "images": imgs}
    if admin:
        d.update({"stock": r["stock"], "active": bool(r["active"])})
    return d


def list_products(store_id: str, admin=False) -> list:
    conn = db.get_connection()
    try:
        _ensure(conn)
        expire_stale(conn)
        q = "SELECT * FROM shop_products WHERE store_id = ?" + ("" if admin else " AND active = 1") + " ORDER BY category, name"
        return [_product_public(conn, r, admin) for r in conn.execute(q, (store_id,)).fetchall()]
    finally:
        conn.close()


def get_product(product_id: str):
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("""SELECT p.* FROM shop_products p JOIN shop_stores s ON s.store_id = p.store_id
                            WHERE p.product_id = ? AND p.active = 1 AND s.active = 1""", (product_id,)).fetchone()
        return _product_public(conn, r) if r else None
    finally:
        conn.close()


# ───────────────────────── orders ─────────────────────────
def _new_order_id(conn) -> str:
    for _ in range(20):
        oid = "KHU-" + "".join(secrets.choice(_CODE_CHARS) for _ in range(6))
        if not conn.execute("SELECT 1 FROM shop_orders WHERE order_id = ?", (oid,)).fetchone():
            return oid
    raise RuntimeError("could not make an order code")


def _release_stock(conn, order_row):
    """Give the reserved items back, once."""
    if not order_row["stock_held"]:
        return
    for it in json.loads(order_row["items_json"]):
        conn.execute("UPDATE shop_products SET stock = stock + ? WHERE product_id = ?", (int(it["qty"]), it["product_id"]))
    conn.execute("UPDATE shop_orders SET stock_held = 0 WHERE order_id = ?", (order_row["order_id"],))


def expire_stale(conn=None):
    """Unpaid orders older than the hold time become 'expired' and release their stock."""
    own = conn is None
    conn = conn or db.get_connection()
    try:
        _ensure(conn)
        cutoff = (datetime.now() - timedelta(minutes=ORDER_HOLD_MINUTES)).isoformat()
        for r in conn.execute("SELECT * FROM shop_orders WHERE status = 'pending_payment' AND created_at < ?", (cutoff,)).fetchall():
            _release_stock(conn, r)
            conn.execute("UPDATE shop_orders SET status = 'expired', failure_reason = ?, updated_at = ? WHERE order_id = ? AND status = 'pending_payment'",
                         ("Payment was not completed in time.", _now(), r["order_id"]))
        conn.commit()
    finally:
        if own:
            conn.close()


def create_order(store_id, items, customer_name, phone, town, address, note) -> dict:
    """Validate, price from saved prices, reserve stock. Returns the order (status pending_payment)."""
    import mpesa
    phone = mpesa.normalize_phone(phone)
    if not phone:
        raise ValueError("Enter a Safaricom number like 0712345678 (it receives the M-Pesa request).")
    customer_name, town, address, note = _clean(customer_name, 80), _clean(town, 60), _clean(address, 200), _clean(note, 200)
    if len(customer_name) < 2:
        raise ValueError("Enter your name.")
    if not town or len(address) < 3:
        raise ValueError("Enter the town and where to deliver.")
    merged = {}
    for it in items or []:
        pid, qty = str(it.get("product_id", ""))[:20], int(it.get("qty", 0))
        if qty < 1 or qty > MAX_QTY:
            raise ValueError(f"You can order 1 to {MAX_QTY} of each item.")
        merged[pid] = merged.get(pid, 0) + qty
    if not merged or len(merged) > MAX_LINES:
        raise ValueError(f"Add between 1 and {MAX_LINES} different items.")
    conn = db.get_connection()
    try:
        _ensure(conn)
        expire_stale(conn)
        store = conn.execute("SELECT * FROM shop_stores WHERE store_id = ? AND active = 1", (store_id,)).fetchone()
        if not store:
            raise ValueError("That store is not available.")
        # Anyone can type any number, so cap how often one phone can be sent payment requests.
        hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        if conn.execute("SELECT COUNT(*) AS n FROM shop_orders WHERE phone = ? AND status = 'pending_payment'", (phone,)).fetchone()["n"] >= 1:
            raise ValueError("This number already has a payment waiting. Finish it on your phone, or wait a few minutes and try again.")
        if conn.execute("SELECT COUNT(*) AS n FROM shop_orders WHERE phone = ? AND created_at > ?", (phone, hour_ago)).fetchone()["n"] >= 3:
            raise ValueError("Too many payment requests for this number. Please wait an hour and try again.")
        lines, subtotal = [], 0
        for pid, qty in merged.items():
            p = conn.execute("SELECT * FROM shop_products WHERE product_id = ? AND store_id = ? AND active = 1", (pid, store_id)).fetchone()
            if not p:
                raise ValueError("One of the items is no longer available. Please refresh the shop.")
            if qty > MAX_QTY:
                raise ValueError(f"You can order 1 to {MAX_QTY} of each item.")
            cur = conn.execute("UPDATE shop_products SET stock = stock - ? WHERE product_id = ? AND stock >= ?", (qty, pid, qty))
            if not cur.rowcount:
                raise ValueError(f"Sorry, {p['name']} does not have {qty} left in stock.")
            lines.append({"product_id": pid, "name": p["name"], "brand": p["brand"] or "", "price": p["price"], "qty": qty})
            subtotal += p["price"] * qty
        fee = store["delivery_fee"] or 0
        oid, now = _new_order_id(conn), _now()
        conn.execute("""INSERT INTO shop_orders (order_id, store_id, store_name, customer_name, phone, town, address, note, items_json,
                        subtotal, delivery_fee, total, status, stock_held, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (oid, store_id, store["name"], customer_name, phone, town, address, note, json.dumps(lines),
                      subtotal, fee, subtotal + fee, "pending_payment", 1, now, now))
        conn.commit()
        return {"order_id": oid, "phone": phone, "total": subtotal + fee, "subtotal": subtotal, "delivery_fee": fee, "store_name": store["name"]}
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def attach_checkout(order_id: str, checkout_request_id: str, merchant_request_id: str):
    conn = db.get_connection()
    try:
        _ensure(conn)
        conn.execute("UPDATE shop_orders SET checkout_request_id = ?, merchant_request_id = ?, updated_at = ? WHERE order_id = ?",
                     (checkout_request_id, merchant_request_id, _now(), order_id))
        conn.commit()
    finally:
        conn.close()


def fail_order(order_id: str, reason: str):
    """Payment could not start or was declined: release the stock."""
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("SELECT * FROM shop_orders WHERE order_id = ? AND status = 'pending_payment'", (order_id,)).fetchone()
        if r:
            _release_stock(conn, r)
            conn.execute("UPDATE shop_orders SET status = 'failed', failure_reason = ?, updated_at = ? WHERE order_id = ?",
                         (_clean(reason, 160), _now(), order_id))
            conn.commit()
    finally:
        conn.close()


def apply_payment_result(checkout_request_id: str, ok: bool, reason: str = "", receipt: str = "", amount=None, require_amount: bool = False) -> str:
    """Record Safaricom's verdict. Idempotent. Returns paid / failed / ignored / amount_mismatch."""
    if not checkout_request_id:
        return "ignored"
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("SELECT * FROM shop_orders WHERE checkout_request_id = ?", (checkout_request_id,)).fetchone()
        if not r or r["status"] not in ("pending_payment", "expired", "failed"):
            return "ignored"
        if ok:
            if amount is None and require_amount:
                # A success report with no amount cannot be checked: never mark it paid on its word alone.
                conn.execute("UPDATE shop_orders SET admin_note = ?, updated_at = ? WHERE order_id = ?",
                             ("A payment report arrived without an amount: check M-Pesa before sending the goods.", _now(), r["order_id"]))
                conn.commit()
                return "amount_mismatch"
            if amount is not None and int(round(float(amount))) != int(r["total"]):
                conn.execute("UPDATE shop_orders SET admin_note = ?, updated_at = ? WHERE order_id = ?",
                             (f"Payment of {amount} received but the order total is {r['total']}: check M-Pesa {receipt}.", _now(), r["order_id"]))
                conn.commit()
                return "amount_mismatch"
            if r["status"] != "pending_payment":
                # Paid after we gave up on it (late callback): take the stock again if we can, otherwise flag it for a refund.
                ok_stock = True
                for it in json.loads(r["items_json"]):
                    cur = conn.execute("UPDATE shop_products SET stock = stock - ? WHERE product_id = ? AND stock >= ?",
                                       (int(it["qty"]), it["product_id"], int(it["qty"])))
                    ok_stock = ok_stock and bool(cur.rowcount)
                note = "" if ok_stock else "Paid after the hold expired and some items are out of stock: refund or fulfil by hand."
                conn.execute("UPDATE shop_orders SET stock_held = ?, admin_note = ? WHERE order_id = ?", (1 if ok_stock else 0, note, r["order_id"]))
            conn.execute("UPDATE shop_orders SET status = 'paid', mpesa_receipt = ?, failure_reason = '', updated_at = ? WHERE order_id = ?",
                         (_clean(receipt, 30), _now(), r["order_id"]))
            conn.commit()
            return "paid"
        if r["status"] == "pending_payment":
            _release_stock(conn, r)
            conn.execute("UPDATE shop_orders SET status = 'failed', failure_reason = ?, updated_at = ? WHERE order_id = ?",
                         (_clean(reason or "Payment was not completed.", 160), _now(), r["order_id"]))
            conn.commit()
            return "failed"
        return "ignored"
    finally:
        conn.close()


def _order_public(r) -> dict:
    return {"order_id": r["order_id"], "store_name": r["store_name"], "status": r["status"], "items": json.loads(r["items_json"]),
            "subtotal": r["subtotal"], "delivery_fee": r["delivery_fee"], "total": r["total"], "town": r["town"],
            "failure_reason": r["failure_reason"] or "", "mpesa_receipt": r["mpesa_receipt"] or "", "created_at": r["created_at"]}


def get_order_for_customer(order_id: str, phone: str):
    import mpesa
    p = mpesa.normalize_phone(phone)
    conn = db.get_connection()
    try:
        _ensure(conn)
        expire_stale(conn)
        r = conn.execute("SELECT * FROM shop_orders WHERE order_id = ?", (order_id[:12].upper(),)).fetchone()
        if not r or not p or r["phone"] != p:
            return None, None
        return _order_public(r), r["checkout_request_id"] if r["status"] == "pending_payment" else None
    finally:
        conn.close()


def _order_admin(r) -> dict:
    d = _order_public(r)
    d.update({"store_id": r["store_id"], "customer_name": r["customer_name"], "phone": r["phone"], "address": r["address"],
              "note": r["note"] or "", "admin_note": r["admin_note"] or "", "updated_at": r["updated_at"]})
    return d


def list_orders(status: str = "", store_id: str = "", limit: int = 200) -> list:
    conn = db.get_connection()
    try:
        _ensure(conn)
        expire_stale(conn)
        q, args = "SELECT * FROM shop_orders WHERE 1=1", []
        if status in STATUSES:
            q += " AND status = ?"; args.append(status)
        if store_id:
            q += " AND store_id = ?"; args.append(store_id)
        q += " ORDER BY created_at DESC"
        return [_order_admin(r) for r in conn.execute(q, tuple(args)).fetchall()[:max(1, min(limit, 500))]]
    finally:
        conn.close()


def set_fulfilment(order_id: str, status: str, note: str = "") -> str:
    if status not in ADMIN_STEPS:
        raise ValueError("Choose processing, shipped, delivered or cancelled.")
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("SELECT * FROM shop_orders WHERE order_id = ?", (order_id,)).fetchone()
        if not r:
            raise ValueError("Order not found.")
        if r["status"] not in ADMIN_STEPS[status]:
            raise ValueError(f"A {r['status'].replace('_', ' ')} order cannot be marked {status}.")
        if status == "cancelled" and r["status"] in ("paid", "processing"):
            _release_stock(conn, r)
        extra = _clean(note, 200)
        if status == "cancelled":
            ref = f" for M-Pesa {r['mpesa_receipt']}" if r["mpesa_receipt"] else f" ({r['total']} KES, paid by {r['phone']})"
            extra = (extra + " " if extra else "") + f"REFUND DUE{ref}."
        conn.execute("UPDATE shop_orders SET status = ?, admin_note = ?, updated_at = ? WHERE order_id = ?",
                     (status, extra or r["admin_note"] or "", _now(), order_id))
        conn.commit()
        return status
    finally:
        conn.close()


def settlement_summary() -> list:
    """Money taken per store from paid, not cancelled orders (what you owe each store before your own fee)."""
    conn = db.get_connection()
    try:
        _ensure(conn)
        out = []
        for s in conn.execute("SELECT store_id, name FROM shop_stores ORDER BY name").fetchall():
            rows = conn.execute("SELECT status, total, delivery_fee FROM shop_orders WHERE store_id = ?", (s["store_id"],)).fetchall()
            paid = [x for x in rows if x["status"] in ("paid", "processing", "shipped", "delivered")]
            out.append({"store_id": s["store_id"], "name": s["name"], "orders_paid": len(paid),
                        "amount_paid": sum(x["total"] for x in paid),
                        "pending": sum(1 for x in rows if x["status"] == "pending_payment"),
                        "to_fulfil": sum(1 for x in rows if x["status"] in ("paid", "processing")),
                        "refunds_due": sum(1 for x in rows if x["status"] == "cancelled")})
        return out
    finally:
        conn.close()


# ───────────────────────── backups ─────────────────────────
def export_all() -> dict:
    conn = db.get_connection()
    try:
        _ensure(conn)
        t = lambda n: [dict(r) for r in conn.execute(f"SELECT * FROM {n}").fetchall()]
        return {"stores": t("shop_stores"), "products": t("shop_products"), "images": t("shop_images"), "orders": t("shop_orders")}
    finally:
        conn.close()


def import_all(data) -> dict:
    """Restore: anything already there is kept as it is."""
    out = {"shop_stores": 0, "shop_products": 0, "shop_images": 0, "shop_orders": 0}
    if not isinstance(data, dict):
        return out
    spec = (("stores", "shop_stores", "store_id"), ("products", "shop_products", "product_id"),
            ("images", "shop_images", "image_id"), ("orders", "shop_orders", "order_id"))
    conn = db.get_connection()
    try:
        _ensure(conn)
        for key, table, pk in spec:
            for row in data.get(key) or []:
                if not isinstance(row, dict) or not row.get(pk):
                    continue
                if conn.execute(f"SELECT 1 FROM {table} WHERE {pk} = ?", (row[pk],)).fetchone():
                    continue
                names = [k for k in row.keys() if re.fullmatch(r"[a-z_0-9]+", k)]
                try:
                    conn.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", tuple(row[k] for k in names))
                    out[table] += 1
                except Exception:  # noqa: BLE001 - a row from an older/newer shape is skipped, never fatal
                    _rollback(conn)
        conn.commit()
    finally:
        conn.close()
    return out


def count_open(order_ids) -> int:
    """How many of these orders are still waiting for payment (used to cap unpaid orders per visitor)."""
    ids = [str(i)[:12] for i in (order_ids or [])][:20]
    if not ids:
        return 0
    conn = db.get_connection()
    try:
        _ensure(conn)
        expire_stale(conn)
        q = ",".join("?" for _ in ids)
        return conn.execute(f"SELECT COUNT(*) AS n FROM shop_orders WHERE status = 'pending_payment' AND order_id IN ({q})", tuple(ids)).fetchone()["n"]
    finally:
        conn.close()


def reconcile(query, max_orders: int = 15) -> dict:
    """Ask Safaricom about orders whose payment report may have been lost (callback missed while the server restarted).
    Covers orders still waiting for more than 40 seconds and orders that timed out in the last 90 minutes, since a late
    payment on those is still money to deal with. `query(checkout_request_id)` returns {state, reason, receipt}."""
    now = datetime.now()
    waiting_before = (now - timedelta(seconds=40)).isoformat()
    expired_after = (now - timedelta(minutes=90)).isoformat()
    conn = db.get_connection()
    try:
        _ensure(conn)
        expire_stale(conn)
        rows = conn.execute(
            """SELECT checkout_request_id FROM shop_orders WHERE checkout_request_id != '' AND checkout_request_id IS NOT NULL AND
               ((status = 'pending_payment' AND created_at < ?) OR (status = 'expired' AND updated_at > ?))
               ORDER BY created_at LIMIT ?""", (waiting_before, expired_after, int(max_orders))).fetchall()
        ids = [r["checkout_request_id"] for r in rows]
    finally:
        conn.close()
    out = {"checked": 0, "paid": 0, "failed": 0, "errors": 0}
    for cid in ids:
        try:
            q = query(cid)
            out["checked"] += 1
            if q.get("state") == "pending":
                continue
            res = apply_payment_result(cid, q.get("state") == "paid", q.get("reason", ""), q.get("receipt", ""), None)
            if res in ("paid", "failed"):
                out[res] += 1
        except Exception:  # noqa: BLE001 - Safaricom busy: try again next minute
            out["errors"] += 1
    return out
