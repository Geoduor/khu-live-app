"""
database.py — Persistent cache for KHU scraped data
Uses SQLite so data survives backend restarts.
If a live scrape fails, we serve the last-known-good data
and tell the frontend how old it is (exactly how ESPN/SofaScore behave).
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "khu_cache.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist yet. Safe to call every startup."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS standings_cache (
            league_key   TEXT PRIMARY KEY,
            data_json    TEXT NOT NULL,
            scraped_at   TEXT NOT NULL,
            success      INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fixtures_results_cache (
            id           INTEGER PRIMARY KEY CHECK (id = 1),
            data_json    TEXT NOT NULL,
            scraped_at   TEXT NOT NULL,
            success      INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ── Circuit breaker state — survives backend restarts ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS circuit_breaker (
            id                  INTEGER PRIMARY KEY CHECK (id = 1),
            state               TEXT NOT NULL DEFAULT 'CLOSED',
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            opened_at           TEXT,
            last_manual_refresh TEXT
        )
    """)
    cur.execute("""
        INSERT OR IGNORE INTO circuit_breaker (id, state, consecutive_failures)
        VALUES (1, 'CLOSED', 0)
    """)

    conn.commit()
    conn.close()
    logger.info(f"Database ready at {DB_PATH}")


def save_standings(league_key: str, data: dict, success: bool = True):
    """Save (or overwrite) standings for one league."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO standings_cache (league_key, data_json, scraped_at, success)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(league_key) DO UPDATE SET
            data_json = excluded.data_json,
            scraped_at = excluded.scraped_at,
            success = excluded.success
    """, (league_key, json.dumps(data), datetime.now().isoformat(), int(success)))
    conn.commit()
    conn.close()


def load_standings(league_key: str):
    """Load cached standings for one league. Returns None if never cached."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM standings_cache WHERE league_key = ?", (league_key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    data = json.loads(row["data_json"])
    data["_cache_scraped_at"] = row["scraped_at"]
    data["_cache_success"] = bool(row["success"])
    return data


def load_all_standings():
    """Load every cached league at once (used on backend startup)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM standings_cache")
    rows = cur.fetchall()
    conn.close()
    result = {}
    for row in rows:
        data = json.loads(row["data_json"])
        data["_cache_scraped_at"] = row["scraped_at"]
        data["_cache_success"] = bool(row["success"])
        result[row["league_key"]] = data
    return result


def save_fixtures_results(data: dict, success: bool = True):
    """Save the homepage fixtures/results scrape (single row table)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO fixtures_results_cache (id, data_json, scraped_at, success)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            data_json = excluded.data_json,
            scraped_at = excluded.scraped_at,
            success = excluded.success
    """, (json.dumps(data), datetime.now().isoformat(), int(success)))
    conn.commit()
    conn.close()


def load_fixtures_results():
    """Load cached fixtures/results. Returns None if never cached."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fixtures_results_cache WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    data = json.loads(row["data_json"])
    data["_cache_scraped_at"] = row["scraped_at"]
    data["_cache_success"] = bool(row["success"])
    return data


def cache_age_seconds(scraped_at_iso: str) -> float:
    """How many seconds old is this cached timestamp."""
    try:
        scraped_dt = datetime.fromisoformat(scraped_at_iso)
        return (datetime.now() - scraped_dt).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


# ══════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ══════════════════════════════════════════════════════
# States: CLOSED (normal) -> OPEN (tripped, skip requests) -> HALF_OPEN (test) -> CLOSED or OPEN
# Global breaker for kenyahockeyunion.org as a whole, since all 8 leagues
# share the same server — if one times out due to server issues, they all will.

def get_circuit_state() -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM circuit_breaker WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"state": "CLOSED", "consecutive_failures": 0, "opened_at": None, "last_manual_refresh": None}
    return dict(row)


def record_scrape_result(success: bool, failure_threshold: int = 3):
    """
    Call this after every real scrape attempt (not manual-refresh test pings).
    Trips the circuit to OPEN once `failure_threshold` consecutive failures occur.
    A single success immediately resets everything back to CLOSED.
    """
    conn = get_connection()
    cur = conn.cursor()
    current = get_circuit_state()

    if success:
        cur.execute("""
            UPDATE circuit_breaker SET state = 'CLOSED', consecutive_failures = 0, opened_at = NULL
            WHERE id = 1
        """)
    else:
        new_failures = current["consecutive_failures"] + 1
        if new_failures >= failure_threshold and current["state"] != "OPEN":
            cur.execute("""
                UPDATE circuit_breaker
                SET state = 'OPEN', consecutive_failures = ?, opened_at = ?
                WHERE id = 1
            """, (new_failures, datetime.now().isoformat()))
            logger.warning(f"🔴 Circuit breaker TRIPPED OPEN after {new_failures} consecutive failures")
        else:
            cur.execute("""
                UPDATE circuit_breaker SET consecutive_failures = ? WHERE id = 1
            """, (new_failures,))

    conn.commit()
    conn.close()


def should_attempt_scrape(cooldown_seconds: int = 300) -> bool:
    """
    Call this BEFORE attempting a scheduled (automatic) scrape.
    Returns False if the circuit is OPEN and still within cooldown —
    meaning: skip the real request entirely, serve cache instead.
    Returns True if CLOSED, or if OPEN but cooldown has elapsed
    (caller should treat this as a HALF_OPEN test attempt).
    """
    state = get_circuit_state()
    if state["state"] != "OPEN":
        return True

    if not state["opened_at"]:
        return True  # safety fallback — malformed state, allow attempt

    age = cache_age_seconds(state["opened_at"])
    if age >= cooldown_seconds:
        logger.info(f"🟡 Circuit breaker entering HALF_OPEN — cooldown elapsed ({age:.0f}s), allowing test request")
        return True

    logger.info(f"⚪ Circuit breaker OPEN — skipping scrape, {cooldown_seconds - age:.0f}s left in cooldown")
    return False


def record_manual_refresh():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE circuit_breaker SET last_manual_refresh = ? WHERE id = 1", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()


def can_manual_refresh(min_interval_seconds: int = 10) -> bool:
    """Rate-limit manual refresh so button-mashing can't hammer KHU either."""
    state = get_circuit_state()
    if not state.get("last_manual_refresh"):
        return True
    age = cache_age_seconds(state["last_manual_refresh"])
    return age >= min_interval_seconds
