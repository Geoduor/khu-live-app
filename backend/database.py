"""
database.py — Persistent cache for KHU scraped data
Uses SQLite so data survives backend restarts.
If a live scrape fails, we serve the last-known-good data
and tell the frontend how old it is (exactly how ESPN/SofaScore behave).
"""

import sqlite3
import json
import logging
import hashlib
import secrets
from datetime import datetime, timedelta
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

    # ── PDF-sourced fixtures, stored SEPARATELY from the live-scrape cache. ──
    # This is the source of truth for "fixtures KHU published as PDF but
    # hasn't put on the live site yet." Every fixtures/results refresh
    # (scheduled every 15 min, or manual) re-merges this table's contents
    # into the fresh scrape output — so PDF fixtures survive indefinitely,
    # even through refresh cycles where the live site itself returns
    # nothing (e.g. during a genuine data gap on KHU's site).
    # Keyed by (league_short, home_team, away_team, date) via match_key so
    # re-uploading the same or an updated PDF just upserts, never duplicates.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdf_fixtures_store (
            match_key    TEXT PRIMARY KEY,
            data_json    TEXT NOT NULL,
            uploaded_at  TEXT NOT NULL,
            source_file  TEXT
        )
    """)

    # ── Manually-entered results — same "fills gaps, never overwrites
    # live data" philosophy as pdf_fixtures_store above, applied to
    # RESULTS instead of fixtures. Exists because scraping results has
    # repeatedly proven fragile (see main.py's refresh_fixtures_results
    # docstring for the full history) — this gives a human a direct way
    # to record a result KHU's site hasn't reflected yet, without
    # waiting on scraper fixes. Whichever source (manual entry or live
    # scrape) has a given match FIRST is what keeps showing — see
    # merge_manual_results_into_scraped in main.py for the exact rule.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS manual_results_store (
            match_key    TEXT PRIMARY KEY,
            data_json    TEXT NOT NULL,
            entered_at   TEXT NOT NULL
        )
    """)

    # ── Manual team-stat corrections ──
    # Unlike fixtures/results (discrete events, "fills gaps"), a team's
    # standings row always exists once any scrape has succeeded — so a
    # manual entry here represents a CORRECTION (overrides the live-
    # scraped value for whichever fields were actually provided), not a
    # gap-filler. Keyed by (league_short, team_name) — one row per team
    # per league.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS manual_team_stats_store (
            stat_key    TEXT PRIMARY KEY,
            data_json   TEXT NOT NULL,
            entered_at  TEXT NOT NULL
        )
    """)

    # ── Manual player-stat entries ──
    # KHU's site doesn't publish individual player statistics at all —
    # this isn't a scraper gap to fill, it's tracking something that
    # simply doesn't exist elsewhere. One row per (league, team, player)
    # holding season-to-date totals, directly set/corrected by an admin
    # or agent (e.g. after aggregating from matchday scorer/card sheets).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS manual_player_stats_store (
            stat_key    TEXT PRIMARY KEY,
            data_json   TEXT NOT NULL,
            entered_at  TEXT NOT NULL
        )
    """)

    # ── Agents — people (besides you) allowed to add manual results. ──
    # Each has their own login, so every result can be attributed to a
    # real person instead of an anonymous shared token — useful for
    # accountability and for tracking down a mistake later. Passwords
    # are stored as salted PBKDF2-SHA256 hashes (Python's stdlib
    # hashlib/secrets — no extra dependency to install or keep pinned
    # on Render), never in plain text.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            username      TEXT PRIMARY KEY,
            display_name  TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL
        )
    """)

    # ── Agent login sessions ──
    # A logged-in agent gets an opaque session token (not a JWT — no
    # extra dependency needed) valid for 30 days, checked against this
    # table on every write. Deactivating an agent (see agents.active)
    # doesn't need to touch existing sessions — the auth check joins
    # against agents.active every time, so deactivation takes effect
    # immediately even for someone already logged in.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            token       TEXT PRIMARY KEY,
            username    TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL
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
    """Save (or overwrite) standings for one league.

    A FAILED scrape (success=False) must never overwrite the
    last-known-good payload — otherwise a restart while KHU is down
    would boot into empty error payloads instead of the data users
    could still see. Failed scrapes leave the existing good row
    untouched (the in-memory cache already does the same)."""
    conn = get_connection()
    cur = conn.cursor()
    if not success:
        cur.execute("SELECT success FROM standings_cache WHERE league_key = ?", (league_key,))
        row = cur.fetchone()
        if row and row["success"]:
            conn.close()
            return
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
    """Save the homepage fixtures/results scrape (single row table).
    Same rule as save_standings: a failed scrape never overwrites the
    last-known-good payload, so a restart can always serve real data."""
    conn = get_connection()
    cur = conn.cursor()
    if not success:
        cur.execute("SELECT success FROM fixtures_results_cache WHERE id = 1")
        row = cur.fetchone()
        if row and row["success"]:
            conn.close()
            return
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


def _pdf_match_key(match: dict) -> str:
    """Same identity rule as pdf_fixtures.merge_pdf_fixtures_into_scraped's
    sig() — league + both teams + calendar date (not kickoff time), so a
    re-uploaded/corrected PDF updates the existing row instead of duplicating."""
    date_part = (match.get("date") or "")[:10]
    return "|".join([
        match.get("league_short", "").strip().upper(),
        match.get("home_team", "").strip().lower(),
        match.get("away_team", "").strip().lower(),
        date_part,
    ])


def save_pdf_fixtures(matches: list, source_file: str = ""):
    """
    Upsert PDF-sourced fixtures into permanent storage (separate from the
    live-scrape cache). Uploading a new/updated PDF calls this — existing
    rows with a matching key get overwritten (e.g. a venue or time
    correction in a new PDF version), everything else is added.
    """
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    for m in matches:
        key = _pdf_match_key(m)
        cur.execute("""
            INSERT INTO pdf_fixtures_store (match_key, data_json, uploaded_at, source_file)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(match_key) DO UPDATE SET
                data_json = excluded.data_json,
                uploaded_at = excluded.uploaded_at,
                source_file = excluded.source_file
        """, (key, json.dumps(m), now, source_file))
    conn.commit()
    conn.close()


def load_pdf_fixtures() -> list:
    """Load every PDF-sourced fixture ever uploaded. Returns [] if none."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT data_json FROM pdf_fixtures_store")
    rows = cur.fetchall()
    conn.close()
    return [json.loads(row["data_json"]) for row in rows]


def clear_pdf_fixtures():
    """Wipe all stored PDF fixtures. Useful if a bad PDF got uploaded by mistake."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM pdf_fixtures_store")
    conn.commit()
    conn.close()


def _manual_result_key(result: dict) -> str:
    """Same identity rule as _pdf_match_key — league + both teams +
    calendar date (not kickoff time) — so re-submitting a correction
    for the same match upserts instead of creating a duplicate."""
    date_part = (result.get("date") or "")[:10]
    return "|".join([
        result.get("league_short", "").strip().upper(),
        result.get("home_team", "").strip().lower(),
        result.get("away_team", "").strip().lower(),
        date_part,
    ])


def save_manual_result(result: dict) -> str:
    """Upsert one manually-entered result. Returns its match_key (used
    as the ID for later editing/deleting via the admin endpoints)."""
    conn = get_connection()
    cur = conn.cursor()
    key = _manual_result_key(result)
    cur.execute("""
        INSERT INTO manual_results_store (match_key, data_json, entered_at)
        VALUES (?, ?, ?)
        ON CONFLICT(match_key) DO UPDATE SET
            data_json = excluded.data_json,
            entered_at = excluded.entered_at
    """, (key, json.dumps(result), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return key


def load_manual_results() -> list:
    """Load every manually-entered result. Returns [] if none. Each
    dict includes its own match_key (added here, not stored inside
    data_json) so the admin UI can reference it for deletion."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT match_key, data_json FROM manual_results_store")
    rows = cur.fetchall()
    conn.close()
    results = []
    for row in rows:
        r = json.loads(row["data_json"])
        r["match_key"] = row["match_key"]
        results.append(r)
    return results


def delete_manual_result(match_key: str) -> bool:
    """Remove one manually-entered result (e.g. to fix a typo by
    re-entering it, or because it was added in error). Returns True if
    a row was actually deleted, False if that key didn't exist."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM manual_results_store WHERE match_key = ?", (match_key,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ══════════════════════════════════════════════════════
# MANUAL TEAM STATS — corrections to a team's standings row
# ══════════════════════════════════════════════════════

def _team_stat_key(league_short: str, team_name: str) -> str:
    return f"{league_short.strip().upper()}|{team_name.strip().lower()}"


def save_team_stats(league_short: str, team_name: str, stats: dict) -> str:
    """Upsert a correction for one team's standings row. `stats` holds
    only the fields being overridden (e.g. just {"points": 18} to fix
    one wrong number) — see apply_team_stat_overrides in main.py for how
    partial overrides are merged onto the live-scraped row."""
    conn = get_connection()
    cur = conn.cursor()
    key = _team_stat_key(league_short, team_name)
    record = {"league_short": league_short.strip().upper(), "team_name": team_name.strip(), **stats}
    cur.execute("""
        INSERT INTO manual_team_stats_store (stat_key, data_json, entered_at)
        VALUES (?, ?, ?)
        ON CONFLICT(stat_key) DO UPDATE SET
            data_json = excluded.data_json,
            entered_at = excluded.entered_at
    """, (key, json.dumps(record), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return key


def load_team_stats() -> list:
    """Load every manual team-stat correction. Each dict includes its
    own stat_key for later deletion."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT stat_key, data_json FROM manual_team_stats_store")
    rows = cur.fetchall()
    conn.close()
    out = []
    for row in rows:
        r = json.loads(row["data_json"])
        r["stat_key"] = row["stat_key"]
        out.append(r)
    return out


def set_manual_result_table_applied(match_key: str, applied: bool) -> bool:
    """Mark a manual result as having its standings effect applied (or not)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT data_json FROM manual_results_store WHERE match_key = ?", (match_key,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    data = json.loads(row["data_json"])
    data["table_applied"] = applied
    cur.execute("UPDATE manual_results_store SET data_json = ? WHERE match_key = ?", (json.dumps(data), match_key))
    conn.commit()
    conn.close()
    return True


def delete_team_stats(stat_key: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM manual_team_stats_store WHERE stat_key = ?", (stat_key,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ══════════════════════════════════════════════════════
# MANUAL PLAYER STATS — season totals KHU's site doesn't publish
# ══════════════════════════════════════════════════════

def _player_stat_key(league_short: str, team_name: str, player_name: str) -> str:
    return f"{league_short.strip().upper()}|{team_name.strip().lower()}|{player_name.strip().lower()}"


def save_player_stats(league_short: str, team_name: str, player_name: str, stats: dict) -> str:
    """Upsert one player's season-to-date stat line."""
    conn = get_connection()
    cur = conn.cursor()
    key = _player_stat_key(league_short, team_name, player_name)
    record = {
        "league_short": league_short.strip().upper(),
        "team_name": team_name.strip(),
        "player_name": player_name.strip(),
        **stats,
    }
    cur.execute("""
        INSERT INTO manual_player_stats_store (stat_key, data_json, entered_at)
        VALUES (?, ?, ?)
        ON CONFLICT(stat_key) DO UPDATE SET
            data_json = excluded.data_json,
            entered_at = excluded.entered_at
    """, (key, json.dumps(record), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return key


def load_player_stats() -> list:
    """Load every player's stat line. Each dict includes its own
    stat_key for later deletion."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT stat_key, data_json FROM manual_player_stats_store")
    rows = cur.fetchall()
    conn.close()
    out = []
    for row in rows:
        r = json.loads(row["data_json"])
        r["stat_key"] = row["stat_key"]
        out.append(r)
    return out


def delete_player_stats(stat_key: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM manual_player_stats_store WHERE stat_key = ?", (stat_key,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ══════════════════════════════════════════════════════
# AGENTS — people allowed to log in and add manual results
# ══════════════════════════════════════════════════════

def _hash_password(password: str, salt: str = None) -> tuple:
    """PBKDF2-SHA256 with a random per-user salt — stdlib only, no
    bcrypt/argon2 dependency to install and keep working on Render.
    100,000 iterations is a reasonable, unremarkable-to-guess cost for
    this use case (small trusted group, not a public sign-up system)."""
    if salt is None:
        salt = secrets.token_hex(16)
    hash_hex = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return hash_hex, salt


def create_agent(username: str, password: str, display_name: str) -> bool:
    """Create a new agent account. Returns False if that username
    already exists (never silently overwrites an existing account —
    use deactivate_agent + create_agent again if you really mean to
    replace one, so it's a deliberate two-step action)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM agents WHERE username = ?", (username,))
    if cur.fetchone():
        conn.close()
        return False
    password_hash, salt = _hash_password(password)
    cur.execute("""
        INSERT INTO agents (username, display_name, password_hash, password_salt, active, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (username, display_name, password_hash, salt, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True


def verify_agent_login(username: str, password: str):
    """Check a username/password pair. Returns the agent's display_name
    on success, or None if the username doesn't exist, is deactivated,
    or the password is wrong. Deliberately returns the same None for
    all three failure cases — never reveals WHICH part was wrong, so a
    login form can't be used to enumerate valid usernames."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM agents WHERE username = ? AND active = 1", (username,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    computed_hash, _ = _hash_password(password, row["password_salt"])
    if not secrets.compare_digest(computed_hash, row["password_hash"]):
        return None
    return row["display_name"]


def list_agents() -> list:
    """List every agent (active or not) — never includes password
    hashes, only what an admin needs to manage accounts."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, display_name, active, created_at FROM agents ORDER BY created_at")
    rows = cur.fetchall()
    conn.close()
    return [{"username": r["username"], "display_name": r["display_name"],
              "active": bool(r["active"]), "created_at": r["created_at"]} for r in rows]


def set_agent_active(username: str, active: bool) -> bool:
    """Deactivate (or reactivate) an agent — takes effect immediately
    for future requests, even ones using an already-issued session
    token, since session validation always re-checks agents.active.
    Deactivating rather than deleting preserves their entered_by
    history on past results. Returns False if that username doesn't exist."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE agents SET active = ? WHERE username = ?", (int(active), username))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def create_agent_session(username: str) -> str:
    """Issue a new opaque session token for an already-authenticated
    agent, valid 30 days."""
    conn = get_connection()
    cur = conn.cursor()
    token = secrets.token_hex(32)
    now = datetime.now()
    cur.execute("""
        INSERT INTO agent_sessions (token, username, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """, (token, username, now.isoformat(), (now + timedelta(days=30)).isoformat()))
    conn.commit()
    conn.close()
    return token


def verify_agent_session(token: str):
    """Check a session token. Returns {"username", "display_name"} if
    valid AND the agent is still active, else None. Expired sessions
    are lazily cleaned up here rather than needing a separate cleanup job."""
    if not token:
        return None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.token, s.username, s.expires_at, a.display_name, a.active
        FROM agent_sessions s JOIN agents a ON a.username = s.username
        WHERE s.token = ?
    """, (token,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now() or not row["active"]:
        cur.execute("DELETE FROM agent_sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        return None
    conn.close()
    return {"username": row["username"], "display_name": row["display_name"]}


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
