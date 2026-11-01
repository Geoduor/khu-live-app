"""
playerprofiles.py — player profile pages (details + photo) for the team squad lists.

A profile adds a few everyday facts to a player who already appears in the app
through stat lines or recorded goal scorers: shirt number, position,
nationality, captain, a short bio and an optional photo. Deliberately NOT
stored: date of birth, address, phone number, school or any contact detail.
Photos must be added with the player's permission (for players under 18, a
parent or guardian's) and can be removed at any time by an admin or agent.
"""
import base64
import hashlib
import threading
from datetime import datetime

import database as db

POSITIONS = ("Goalkeeper", "Defender", "Midfielder", "Forward")
PHOTO_MAX_BYTES = 300_000
_ready = False
_lock = threading.Lock()


def player_id(league_short: str, team_name: str, player_name: str) -> str:
    key = db._player_stat_key(league_short, team_name, player_name)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _ensure(conn):
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        conn.execute("""CREATE TABLE IF NOT EXISTS player_profiles (
            player_id TEXT PRIMARY KEY, league_short TEXT NOT NULL, team_name TEXT NOT NULL, player_name TEXT NOT NULL,
            jersey INTEGER, position TEXT DEFAULT '', nationality TEXT DEFAULT '', captain INTEGER DEFAULT 0,
            bio TEXT DEFAULT '', photo_mime TEXT DEFAULT '', photo_b64 TEXT DEFAULT '',
            updated_at TEXT NOT NULL, updated_by TEXT DEFAULT '')""")
        conn.commit()
        _ready = True


def decode_photo(data_url: str):
    """data:image/...;base64,... -> (mime, base64). PNG, JPEG or WebP only,
    judged by the file's own first bytes. SVG and everything else is refused."""
    import re
    m = re.match(r"^data:image/[a-z+.-]+;base64,([A-Za-z0-9+/=\s]+)$", data_url or "")
    if not m:
        raise ValueError("The photo must be a PNG, JPEG or WebP image.")
    try:
        raw = base64.b64decode(m.group(1), validate=False)
    except Exception:  # noqa: BLE001
        raise ValueError("The photo file could not be read.")
    if len(raw) > PHOTO_MAX_BYTES:
        raise ValueError(f"The photo is too large (max {PHOTO_MAX_BYTES // 1000} KB).")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("The photo must be a PNG, JPEG or WebP image.")
    return mime, base64.b64encode(raw).decode("ascii")


def save_profile(league_short, team_name, player_name, jersey, position, nationality, captain, bio,
                 photo_data_url="", remove_photo=False, by="") -> str:
    player_name, team_name = (player_name or "").strip(), (team_name or "").strip()
    if not player_name or not team_name:
        raise ValueError("Choose the team and type the player's name.")
    if jersey is not None and not (0 <= int(jersey) <= 99):
        raise ValueError("Shirt number must be between 0 and 99.")
    position = (position or "").strip()
    if position and position not in POSITIONS:
        raise ValueError("Position must be Goalkeeper, Defender, Midfielder or Forward.")
    nationality = (nationality or "").strip()[:40]
    bio = " ".join((bio or "").split())[:300]
    pid = player_id(league_short, team_name, player_name)
    conn = db.get_connection()
    try:
        _ensure(conn)
        old = conn.execute("SELECT photo_mime, photo_b64 FROM player_profiles WHERE player_id = ?", (pid,)).fetchone()
        if photo_data_url:
            mime, b64 = decode_photo(photo_data_url)
        elif old and not remove_photo:
            mime, b64 = old["photo_mime"], old["photo_b64"]
        else:
            mime, b64 = "", ""
        now = datetime.now().isoformat()
        conn.execute("""
            INSERT INTO player_profiles (player_id, league_short, team_name, player_name, jersey, position, nationality, captain,
                                         bio, photo_mime, photo_b64, updated_at, updated_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(player_id) DO UPDATE SET jersey=excluded.jersey, position=excluded.position, nationality=excluded.nationality,
              captain=excluded.captain, bio=excluded.bio, photo_mime=excluded.photo_mime, photo_b64=excluded.photo_b64,
              updated_at=excluded.updated_at, updated_by=excluded.updated_by
        """, (pid, league_short.strip().upper(), team_name, player_name, jersey, position, nationality, 1 if captain else 0,
              bio, mime, b64, now, by))
        conn.commit()
        return pid
    finally:
        conn.close()


def delete_profile(pid: str) -> bool:
    conn = db.get_connection()
    try:
        _ensure(conn)
        cur = conn.execute("DELETE FROM player_profiles WHERE player_id = ?", (pid,))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def _row_public(r) -> dict:
    return {"player_id": r["player_id"], "league_short": r["league_short"], "team_name": r["team_name"],
            "player_name": r["player_name"], "jersey": r["jersey"], "position": r["position"] or "",
            "nationality": r["nationality"] or "", "captain": bool(r["captain"]), "bio": r["bio"] or "",
            "has_photo": bool(r["photo_b64"])}


def load_profiles() -> dict:
    """{player_id: public profile dict} (no photo bytes)."""
    conn = db.get_connection()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM player_profiles").fetchall()
        return {r["player_id"]: _row_public(r) for r in rows}
    finally:
        conn.close()


def get_photo(pid: str):
    conn = db.get_connection()
    try:
        _ensure(conn)
        r = conn.execute("SELECT photo_mime, photo_b64 FROM player_profiles WHERE player_id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if not r or not r["photo_b64"]:
        return None
    return r["photo_mime"], base64.b64decode(r["photo_b64"])


def export_all() -> list:
    conn = db.get_connection()
    try:
        _ensure(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM player_profiles ORDER BY player_id").fetchall()]
    finally:
        conn.close()


def import_all(items) -> int:
    """Restore: existing profiles are kept as they are (never overwritten)."""
    n = 0
    conn = db.get_connection()
    try:
        _ensure(conn)
        for r in items if isinstance(items, list) else []:
            if not isinstance(r, dict) or not r.get("player_name") or not r.get("team_name") or not r.get("league_short"):
                continue
            pid = player_id(r["league_short"], r["team_name"], r["player_name"])
            if conn.execute("SELECT 1 FROM player_profiles WHERE player_id = ?", (pid,)).fetchone():
                continue
            mime, b64 = "", ""
            if r.get("photo_b64"):
                try:
                    mime, b64 = decode_photo(f"data:{r.get('photo_mime', 'image/jpeg')};base64,{r['photo_b64']}")
                except ValueError:
                    pass
            pos = r.get("position") if r.get("position") in POSITIONS else ""
            jersey = r.get("jersey") if isinstance(r.get("jersey"), int) and 0 <= r["jersey"] <= 99 else None
            conn.execute("""INSERT INTO player_profiles (player_id, league_short, team_name, player_name, jersey, position, nationality,
                            captain, bio, photo_mime, photo_b64, updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (pid, str(r["league_short"]).upper()[:20], str(r["team_name"])[:120], str(r["player_name"])[:80], jersey, pos,
                          str(r.get("nationality", ""))[:40], 1 if r.get("captain") else 0, str(r.get("bio", ""))[:300],
                          mime, b64, datetime.now().isoformat(), "restore"))
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def add_from_source(league_short, team_name, player_name, jersey=None, photo_bytes=None, by="khu-website") -> str:
    """Create a profile from a public squad list, or fill in only what is still
    blank on an existing one. Anything an admin or agent already set is kept.
    Returns "created", "updated" or "unchanged"."""
    player_name, team_name = " ".join((player_name or "").split())[:80], (team_name or "").strip()
    if not player_name or not team_name or not league_short:
        return "unchanged"
    if jersey is not None and not (0 <= int(jersey) <= 99):
        jersey = None
    mime = b64 = ""
    if photo_bytes:
        try:
            mime, b64 = decode_photo("data:image/jpeg;base64," + base64.b64encode(photo_bytes).decode("ascii"))
        except ValueError:
            mime = b64 = ""
    pid = player_id(league_short, team_name, player_name)
    conn = db.get_connection()
    try:
        _ensure(conn)
        old = conn.execute("SELECT jersey, photo_b64 FROM player_profiles WHERE player_id = ?", (pid,)).fetchone()
        now = datetime.now().isoformat()
        if not old:
            conn.execute("""INSERT INTO player_profiles (player_id, league_short, team_name, player_name, jersey, position,
                            nationality, captain, bio, photo_mime, photo_b64, updated_at, updated_by)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (pid, league_short.strip().upper()[:20], team_name[:120], player_name, jersey, "", "", 0, "", mime, b64, now, by))
            conn.commit()
            return "created"
        sets, args = [], []
        if old["jersey"] is None and jersey is not None:
            sets.append("jersey = ?"); args.append(jersey)
        if not old["photo_b64"] and b64:
            sets += ["photo_mime = ?", "photo_b64 = ?"]; args += [mime, b64]
        if not sets:
            return "unchanged"
        conn.execute(f"UPDATE player_profiles SET {', '.join(sets)}, updated_at = ?, updated_by = ? WHERE player_id = ?",
                     (*args, now, by, pid))
        conn.commit()
        return "updated"
    finally:
        conn.close()
