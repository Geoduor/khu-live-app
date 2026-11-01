"""
insights.py — privacy-friendly analytics and the sponsor slot.

Analytics (no cookies, no personal data stored):
  * Page views and installs are counted per day.
  * "Unique visitors" use a one-way fingerprint of (day, ip, browser) that
    changes every day, so a person can be counted once per day but never
    followed across days, and the IP address is never stored. Fingerprints are
    deleted after 3 days; only the daily totals are kept forever.
  * Browsers that send Do Not Track / Global Privacy Control are not counted.

Sponsor slot: an admin-managed sponsor with a logo and a link, clearly labelled
"Sponsored" in the app. Views and clicks are counted so a sponsor can be shown
real numbers.
"""
import base64
import hashlib
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import database as db

EAT = timezone(timedelta(hours=3))
VIEWS = {"home", "table", "fixtures", "results", "cups", "team", "match", "playoffs", "history", "seasons"}
LOGO_MAX_BYTES = 400_000
_ready = False
_lock = threading.Lock()
_last_prune = {"day": ""}


def today_eat() -> str:
    return datetime.now(EAT).strftime("%Y-%m-%d")


def _ensure(conn):
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        conn.execute("""CREATE TABLE IF NOT EXISTS analytics_daily (
            day TEXT NOT NULL, metric TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, metric))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS analytics_seen (
            day TEXT NOT NULL, vhash TEXT NOT NULL, PRIMARY KEY (day, vhash))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sponsors (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, tagline TEXT DEFAULT '', link_url TEXT NOT NULL,
            logo_mime TEXT DEFAULT '', logo_b64 TEXT DEFAULT '', active INTEGER DEFAULT 1,
            start_date TEXT DEFAULT '', end_date TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.commit()
        _ready = True


def _bump(conn, day: str, metric: str, by: int = 1):
    conn.execute(
        "INSERT INTO analytics_daily (day, metric, n) VALUES (?, ?, ?) "
        "ON CONFLICT(day, metric) DO UPDATE SET n = analytics_daily.n + ?",
        (day, metric, by, by))


def visitor_hash(ip: str, ua: str, day: str) -> str:
    secret = os.environ.get("ADMIN_TOKEN", "") + "|analytics"
    return hashlib.sha256(f"{day}|{secret}|{ip}|{ua[:200]}".encode("utf-8")).hexdigest()[:20]


def record_hit(view: str, ip: str, ua: str):
    """Count one page view (and one unique visitor per day). Never raises."""
    if view not in VIEWS:
        return
    try:
        day = today_eat()
        conn = db.get_connection()
        try:
            _ensure(conn)
            _bump(conn, day, f"view:{view}")
            cur = conn.execute("INSERT OR IGNORE INTO analytics_seen (day, vhash) VALUES (?, ?)",
                               (day, visitor_hash(ip, ua, day)))
            if cur.rowcount == 1:
                _bump(conn, day, "visitors")
            if _last_prune["day"] != day:
                cutoff = (datetime.now(EAT) - timedelta(days=3)).strftime("%Y-%m-%d")
                conn.execute("DELETE FROM analytics_seen WHERE day < ?", (cutoff,))
                _last_prune["day"] = day
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - analytics must never break the app
        pass


def record_event(metric: str):
    """installs, sponsor_imp:<id>, sponsor_click:<id>."""
    try:
        conn = db.get_connection()
        try:
            _ensure(conn)
            _bump(conn, today_eat(), metric)
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def summary(days: int = 30) -> dict:
    days = max(1, min(int(days), 365))
    start = (datetime.now(EAT) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    conn = db.get_connection()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT day, metric, n FROM analytics_daily WHERE day >= ? ORDER BY day", (start,)).fetchall()
    finally:
        conn.close()
    per_day, views, installs = {}, {}, 0
    sponsor = {}
    for r in rows:
        d, m, n = r["day"], r["metric"], r["n"]
        row = per_day.setdefault(d, {"day": d, "visitors": 0, "views": 0, "installs": 0})
        if m == "visitors":
            row["visitors"] += n
        elif m.startswith("view:"):
            row["views"] += n
            views[m[5:]] = views.get(m[5:], 0) + n
        elif m == "installs":
            row["installs"] += n
            installs += n
        elif m.startswith("sponsor_imp:") or m.startswith("sponsor_click:"):
            kind, sid = m.split(":", 1)
            s = sponsor.setdefault(sid, {"impressions": 0, "clicks": 0})
            s["impressions" if kind == "sponsor_imp" else "clicks"] += n
    series = [per_day[d] for d in sorted(per_day)]
    return {
        "days": days,
        "series": series,
        "total_visitor_days": sum(x["visitors"] for x in series),
        "total_views": sum(x["views"] for x in series),
        "views_by_page": dict(sorted(views.items(), key=lambda kv: -kv[1])),
        "installs": installs,
        "sponsor_stats": sponsor,
    }


# ── Sponsors ──────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean_link(url: str) -> str:
    url = (url or "").strip()
    u = urlparse(url)
    if (u.scheme != "https" or not u.hostname or u.username or u.password or len(url) > 300
            or re.search(r"[\s\x00-\x1f]", url)):
        raise ValueError("The link must be a full https:// address, e.g. https://example.com")
    return url


def clean_date(s: str) -> str:
    s = (s or "").strip()
    if s and not _DATE_RE.match(s):
        raise ValueError("Dates must look like 2026-12-31.")
    return s


def decode_logo(data_url: str):
    """data:image/png;base64,... -> (mime, base64). Only PNG, JPEG and WebP
    (checked by the file's own first bytes, not the label). SVG is refused."""
    m = re.match(r"^data:image/[a-z+.-]+;base64,([A-Za-z0-9+/=\s]+)$", data_url or "")
    if not m:
        raise ValueError("The logo must be a PNG, JPEG or WebP image.")
    try:
        raw = base64.b64decode(m.group(1), validate=False)
    except Exception:  # noqa: BLE001
        raise ValueError("The logo file could not be read.")
    if len(raw) > LOGO_MAX_BYTES:
        raise ValueError(f"The logo is too large (max {LOGO_MAX_BYTES // 1000} KB).")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("The logo must be a PNG, JPEG or WebP image.")
    return mime, base64.b64encode(raw).decode("ascii")


def save_sponsor(sponsor_id, name, tagline, link_url, logo_data_url, active, start_date, end_date) -> str:
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ValueError("Give the sponsor a name (up to 80 characters).")
    tagline = (tagline or "").strip()[:120]
    link = clean_link(link_url)
    start, end = clean_date(start_date), clean_date(end_date)
    now = datetime.now().isoformat()
    conn = db.get_connection()
    try:
        _ensure(conn)
        existing = conn.execute("SELECT logo_mime, logo_b64 FROM sponsors WHERE id = ?", (sponsor_id,)).fetchone() if sponsor_id else None
        if logo_data_url:
            mime, b64 = decode_logo(logo_data_url)
        elif existing:
            mime, b64 = existing["logo_mime"], existing["logo_b64"]
        else:
            mime, b64 = "", ""
        if existing:
            conn.execute("""UPDATE sponsors SET name=?, tagline=?, link_url=?, logo_mime=?, logo_b64=?, active=?,
                            start_date=?, end_date=?, updated_at=? WHERE id=?""",
                         (name, tagline, link, mime, b64, 1 if active else 0, start, end, now, sponsor_id))
            sid = sponsor_id
        else:
            sid = secrets.token_hex(6)
            conn.execute("""INSERT INTO sponsors (id, name, tagline, link_url, logo_mime, logo_b64, active, start_date, end_date,
                            created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (sid, name, tagline, link, mime, b64, 1 if active else 0, start, end, now, now))
        conn.commit()
        return sid
    finally:
        conn.close()


def delete_sponsor(sponsor_id: str) -> bool:
    conn = db.get_connection()
    try:
        _ensure(conn)
        cur = conn.execute("DELETE FROM sponsors WHERE id = ?", (sponsor_id,))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def _public(row) -> dict:
    return {"id": row["id"], "name": row["name"], "tagline": row["tagline"], "link_url": row["link_url"],
            "has_logo": bool(row["logo_b64"])}


def list_sponsors(admin: bool = False) -> list:
    """Admin: everything. Public: only sponsors that are on and inside their dates."""
    conn = db.get_connection()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM sponsors ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    today = today_eat()
    out = []
    for r in rows:
        live = bool(r["active"]) and (not r["start_date"] or r["start_date"] <= today) and (not r["end_date"] or r["end_date"] >= today)
        if admin:
            d = _public(r)
            d.update(active=bool(r["active"]), start_date=r["start_date"], end_date=r["end_date"], showing_now=live)
            out.append(d)
        elif live:
            out.append(_public(r))
    return out


def get_logo(sponsor_id: str):
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("SELECT logo_mime, logo_b64 FROM sponsors WHERE id = ?", (sponsor_id,)).fetchone()
    finally:
        conn.close()
    if not r or not r["logo_b64"]:
        return None
    return r["logo_mime"], base64.b64decode(r["logo_b64"])


def sponsor_is_live(sponsor_id: str) -> bool:
    return any(s["id"] == sponsor_id for s in list_sponsors(admin=False))


# ── Backup / restore ──────────────────────────────────────────────────────

def export_all() -> dict:
    conn = db.get_connection()
    try:
        _ensure(conn)
        daily = [dict(r) for r in conn.execute("SELECT day, metric, n FROM analytics_daily ORDER BY day, metric").fetchall()]
        sponsors = [dict(r) for r in conn.execute("SELECT * FROM sponsors ORDER BY created_at").fetchall()]
        return {"analytics_daily": daily, "sponsors": sponsors}
    finally:
        conn.close()


def import_all(data: dict) -> dict:
    """Merge a backup in. Analytics keep the HIGHER count per day/metric (never lower a total)."""
    conn = db.get_connection()
    done = {"analytics_daily": 0, "sponsors": 0}
    try:
        _ensure(conn)
        for r in data.get("analytics_daily") or []:
            if isinstance(r, dict) and isinstance(r.get("n"), int) and r.get("day") and r.get("metric"):
                conn.execute(
                    "INSERT INTO analytics_daily (day, metric, n) VALUES (?, ?, ?) "
                    "ON CONFLICT(day, metric) DO UPDATE SET n = CASE WHEN excluded.n > analytics_daily.n THEN excluded.n ELSE analytics_daily.n END",
                    (str(r["day"])[:10], str(r["metric"])[:80], r["n"]))
                done["analytics_daily"] += 1
        for r in data.get("sponsors") or []:
            if isinstance(r, dict) and r.get("id") and r.get("name") and r.get("link_url"):
                try:
                    clean_link(r["link_url"])
                except ValueError:
                    continue
                if conn.execute("SELECT 1 FROM sponsors WHERE id = ?", (str(r["id"])[:20],)).fetchone():
                    continue
                now = datetime.now().isoformat()
                conn.execute("""INSERT INTO sponsors (id, name, tagline, link_url, logo_mime, logo_b64, active, start_date, end_date,
                                created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                             (str(r["id"])[:20], str(r["name"])[:80], str(r.get("tagline", ""))[:120], r["link_url"],
                              str(r.get("logo_mime", ""))[:30], str(r.get("logo_b64", "")), 1 if r.get("active") else 0,
                              str(r.get("start_date", ""))[:10], str(r.get("end_date", ""))[:10],
                              str(r.get("created_at") or now), now))
                done["sponsors"] += 1
        conn.commit()
    finally:
        conn.close()
    return done
