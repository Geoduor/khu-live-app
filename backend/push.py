"""
push.py — Web Push notification system for the KHU app, with
per-device Favorites/My Teams scoping.

Uses the standard Web Push Protocol (VAPID) — the same mechanism
used by real production PWAs (no native app store needed).

Flow:
  1. Frontend asks user for notification permission
  2. Browser generates a push subscription (endpoint + keys)
  3. Frontend sends that subscription to our backend -> stored in SQLite
  4. User taps stars next to teams they follow -> favorites list is
     attached to that SAME subscription (no login needed — this is
     the same pattern FotMob/SofaScore used before they added accounts)
  5. When a match goes LIVE, we only push to subscriptions that have
     favorited one of the two teams playing — not a global blast
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from pywebpush import webpush, WebPushException
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "khu_cache.db"

# ══════════════════════════════════════════════════════
# VAPID KEYS — loaded from environment variables, never hardcoded
# ══════════════════════════════════════════════════════
VAPID_PRIVATE_KEY_PEM = os.environ.get("VAPID_PRIVATE_KEY_PEM", "").replace("\\n", "\n")
VAPID_PUBLIC_KEY_B64URL = os.environ.get("VAPID_PUBLIC_KEY_B64URL", "")
VAPID_CLAIMS = {
    "sub": f"mailto:{os.environ.get('VAPID_CONTACT_EMAIL', 'khu-app@example.com')}"
}

if not VAPID_PRIVATE_KEY_PEM or not VAPID_PUBLIC_KEY_B64URL:
    logger.warning(
        "⚠️ VAPID keys not found in environment. Push notifications will not work. "
        "Copy .env.example to .env and fill in real keys."
    )


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
            favorite_teams_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration safety: add the column if this is an existing DB from before
    # favorites were introduced (won't error if it already exists)
    try:
        cur.execute("ALTER TABLE push_subscriptions ADD COLUMN favorite_teams_json TEXT NOT NULL DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    conn.close()
    logger.info("Push subscriptions table ready (with favorites support).")


def save_subscription(subscription: dict, favorite_teams: list = None):
    """
    Store a browser's push subscription so we can notify it later.
    If favorite_teams is provided at subscribe time, the subscriber is
    immediately scoped to only those teams (Tier 2). Otherwise they
    default to receiving alerts for every KHU match (Tier 1 — broad),
    until they set favorites later via update_favorite_teams().
    """
    conn = get_connection()
    cur = conn.cursor()
    endpoint = subscription.get("endpoint")
    favorites_json = json.dumps(favorite_teams or [])
    try:
        cur.execute(
            """INSERT INTO push_subscriptions (endpoint, subscription_json, favorite_teams_json)
               VALUES (?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET
                 subscription_json = excluded.subscription_json,
                 favorite_teams_json = excluded.favorite_teams_json""",
            (endpoint, json.dumps(subscription), favorites_json),
        )
        conn.commit()
        logger.info(f"Saved push subscription: {endpoint[:50]}... ({len(favorite_teams or [])} favorites)")
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


def update_favorite_teams(endpoint: str, team_urls: list):
    """
    Update the list of favorited team URLs for a given push subscription.
    team_urls is a list of real kenyahockeyunion.org team page URLs —
    the same team_url values already present in standings/match data.
    Called whenever the user changes their favorites in the app UI.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE push_subscriptions SET favorite_teams_json = ? WHERE endpoint = ?",
        (json.dumps(team_urls), endpoint),
    )
    conn.commit()
    rows_affected = cur.rowcount
    conn.close()
    return rows_affected > 0


def get_favorite_teams(endpoint: str) -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT favorite_teams_json FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return []
    return json.loads(row["favorite_teams_json"])


def send_notification_to_all(title: str, body: str, url: str = "/"):
    """
    Push a notification to EVERY subscribed browser, regardless of favorites.
    Used for global announcements only (e.g. "KHU season starts tomorrow").
    For match-specific alerts, use send_notification_to_favoriters instead.
    """
    subscriptions = get_all_subscriptions()
    return _send_to_subscription_list(subscriptions, title, body, url)


def send_notification_to_favoriters(team_urls: list, title: str, body: str, url: str = "/"):
    """
    Push a notification ONLY to devices that have favorited one of the
    given teams. This is the scoped alert path used when a specific
    match goes LIVE — a Strathmore fan is not bothered by a National
    League SZ match involving teams they don't follow.

    If a subscription has NO favorites set at all, we treat that as
    "notify me about everything" (matches the old global behavior for
    users who haven't picked favorites yet — avoids silently going quiet
    on users who just enabled push and haven't set up favorites).
    """
    team_url_set = set(team_urls)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM push_subscriptions")
    rows = cur.fetchall()
    conn.close()

    targeted = []
    for row in rows:
        favorites = json.loads(row["favorite_teams_json"])
        if not favorites or any(fav in team_url_set for fav in favorites):
            targeted.append(json.loads(row["subscription_json"]))

    return _send_to_subscription_list(targeted, title, body, url)


def _send_to_subscription_list(subscriptions: list, title: str, body: str, url: str):
    if not subscriptions:
        logger.info("No matching push subscriptions — skipping notification.")
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
            if e.response is not None and e.response.status_code in (404, 410):
                remove_subscription(sub.get("endpoint"))

    logger.info(f"Push notification sent: {sent} succeeded, {failed} failed")
    return {"sent": sent, "failed": failed}
