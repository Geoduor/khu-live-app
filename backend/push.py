"""
push.py — Web Push notification system for the KHU app.

Uses the standard Web Push Protocol (VAPID) — the same mechanism
used by real production PWAs (no native app store needed).

Flow:
  1. Frontend asks user for notification permission
  2. Browser generates a push subscription (endpoint + keys)
  3. Frontend sends that subscription to our backend -> stored in SQLite
  4. When a match goes LIVE or a result comes in, backend pushes
     a notification to every stored subscription
"""

import json
import logging
import sqlite3
from pathlib import Path
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "khu_cache.db"

# ══════════════════════════════════════════════════════
# VAPID KEYS
# ══════════════════════════════════════════════════════
# IMPORTANT (honesty note for Geofry):
# These are DEMO keys generated for local development/testing.
# Before deploying to production, generate your OWN keypair with:
#   python -c "from py_vapid import Vapid02; v=Vapid02(); v.generate_keys(); print(v.private_pem().decode())"
# and keep the private key SECRET (never commit it to a public repo).

VAPID_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgcAIC5c/qCniKG2Cj
IyqABph9VePiYAFpiFQ4o55dHlqhRANCAARnDafPfb/Btay2ZdBx36Pgl49beQo3
rxgWALcy1908x7cwoSS4yVbv3PcpkDKvPGEBLfu5NtZGbXNyPDXN5bmB
-----END PRIVATE KEY-----"""

VAPID_PUBLIC_KEY_B64URL = "BGcNp899v8G1rLZl0HHfo-CXj1t5CjevGBYAtzLX3TzHtzChJLjJVu_c9ymQMq88YQEt-7k21kZtc3I8Nc3luYE"

VAPID_CLAIMS = {
    "sub": "mailto:khu-app@example.com"  # update to a real contact before production
}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_push_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT UNIQUE NOT NULL,
            subscription_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Push subscriptions table ready.")


def save_subscription(subscription: dict):
    """Store a browser's push subscription so we can notify it later."""
    conn = get_connection()
    cur = conn.cursor()
    endpoint = subscription.get("endpoint")
    try:
        cur.execute(
            "INSERT OR IGNORE INTO push_subscriptions (endpoint, subscription_json) VALUES (?, ?)",
            (endpoint, json.dumps(subscription)),
        )
        conn.commit()
        logger.info(f"Saved push subscription: {endpoint[:50]}...")
        return True
    finally:
        conn.close()


def remove_subscription(endpoint: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()


def get_all_subscriptions():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM push_subscriptions")
    rows = cur.fetchall()
    conn.close()
    return [json.loads(row["subscription_json"]) for row in rows]


def send_notification_to_all(title: str, body: str, url: str = "/"):
    """
    Push a notification to every subscribed browser.
    Called when a match goes LIVE or finishes, for example.
    Automatically removes subscriptions that are no longer valid (expired/unsubscribed).
    """
    subscriptions = get_all_subscriptions()
    if not subscriptions:
        logger.info("No push subscriptions registered yet — skipping notification.")
        return {"sent": 0, "failed": 0}

    payload = json.dumps({"title": title, "body": body, "url": url})
    sent, failed = 0, 0

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY_PEM,
                vapid_claims=dict(VAPID_CLAIMS),
            )
            sent += 1
        except WebPushException as e:
            failed += 1
            logger.warning(f"Push failed for {sub.get('endpoint','?')[:50]}: {e}")
            # Clean up dead subscriptions (410 Gone / 404 Not Found)
            if e.response is not None and e.response.status_code in (404, 410):
                remove_subscription(sub.get("endpoint"))

    logger.info(f"Push notification sent: {sent} succeeded, {failed} failed")
    return {"sent": sent, "failed": failed}
