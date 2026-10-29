"""
dbconn.py — one place that decides which database the app talks to.

  * DATABASE_URL set (postgresql://…, e.g. Supabase's *session pooler* string)
      -> PostgreSQL, through a small connection pool.
  * DATABASE_URL not set
      -> the local SQLite file, exactly as before.

The rest of the code keeps writing the same SQL it always did. For Postgres this
module translates the few SQLite-only bits (`?` placeholders, INSERT OR IGNORE,
AUTOINCREMENT, ...) and hands back rows that work like sqlite3.Row (row["col"],
row[0], dict(row)). Removing DATABASE_URL puts the app straight back on SQLite.
"""

import logging
import os
import re
import sqlite3
import threading

try:  # so DATABASE_URL in a local .env is honoured
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

logger = logging.getLogger(__name__)

try:
    from psycopg.pq import TransactionStatus
except Exception:  # psycopg only needed when DATABASE_URL is used
    TransactionStatus = None

_pool = None
_pool_url = None
_pool_lock = threading.Lock()


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url if url.startswith(("postgres://", "postgresql://")) else ""


def backend_name() -> str:
    return "postgres" if database_url() else "sqlite"


# ── SQL translation (SQLite dialect -> PostgreSQL) ──────────────────────────
def translate(sql: str) -> str:
    out = sql.replace("%", "%%").replace("?", "%s")
    ignore = re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", out, re.I)
    if ignore:
        out = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", out, flags=re.I)
        out = out.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    out = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "SERIAL PRIMARY KEY", out, flags=re.I)
    out = re.sub(r"\bTEXT\s+DEFAULT\s+CURRENT_TIMESTAMP\b", "TEXT DEFAULT (now()::text)", out, flags=re.I)
    out = re.sub(r"\bADD\s+COLUMN\b(?!\s+IF\s+NOT\s+EXISTS)", "ADD COLUMN IF NOT EXISTS", out, flags=re.I)
    return out


class Row:
    """Behaves like sqlite3.Row: row["name"], row[0], dict(row), iteration over values."""
    __slots__ = ("_k", "_v")

    def __init__(self, keys, values):
        self._k = keys
        self._v = tuple(values)

    def __getitem__(self, i):
        if isinstance(i, (int, slice)):
            return self._v[i]
        try:
            return self._v[self._k.index(i)]
        except ValueError:
            raise IndexError(f"No item with that key: {i!r}") from None

    def keys(self):
        return list(self._k)

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def __repr__(self):
        return f"Row({dict(zip(self._k, self._v))})"


def _row_factory(cursor):
    cols = [d.name for d in cursor.description] if cursor.description else []
    return lambda values: Row(cols, values)


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(translate(sql), tuple(params) if params else None)
        return self

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def __iter__(self):
        return iter(self._cur)


class PgConnection:
    """sqlite3-style connection on top of a pooled psycopg connection."""

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def cursor(self):
        return _PgCursor(self._conn.cursor())

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                # Reads leave a transaction open; end it quietly here so the pool
                # doesn't log a warning for every query. Uncommitted writes are
                # discarded exactly as before.
                if conn.info.transaction_status != TransactionStatus.IDLE:
                    conn.rollback()
                self._pool.putconn(conn)
            except Exception:
                logger.exception("Could not return a database connection to the pool")

    def __del__(self):  # a code path that forgot close() must not starve the pool
        try:
            self.close()
        except Exception:
            pass


def _get_pool(url: str):
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None and _pool_url == url:
            return _pool
        from psycopg_pool import ConnectionPool
        kwargs = {"row_factory": _row_factory, "prepare_threshold": None}
        if "sslmode" not in url and "supabase" in url:
            kwargs["sslmode"] = "require"
        _pool = ConnectionPool(
            url, min_size=1, max_size=int(os.environ.get("DB_POOL_MAX", "5")),
            kwargs=kwargs, timeout=20, check=ConnectionPool.check_connection, open=True,
        )
        _pool_url = url
        logger.info("Connected to PostgreSQL (pooled).")
        return _pool


def connect(sqlite_path):
    """Return a connection for whichever database is configured."""
    url = database_url()
    if url:
        pool = _get_pool(url)
        return PgConnection(pool, pool.getconn())
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn
