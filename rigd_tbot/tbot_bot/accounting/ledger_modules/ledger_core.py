# tbot_bot/accounting/ledger_modules/ledger_core.py

"""
Core ledger DB helpers (v048):
- get_conn(): open SQLite connection using resolver-derived DSN
- tx_context(): atomic transaction context (commit/rollback)
- row factory defaults, busy_timeout, WAL, foreign_keys=ON
- UTC helpers: now_utc(), now_utc_iso(), to_utc(), to_utc_iso()
- No direct Paths/decrypts; identity via utils_identity
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Tuple, Optional, Any

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity


# ---------------------------
# Identity helpers
# ---------------------------

def get_identity_tuple() -> Tuple[str, str, str, str]:
    """
    (entity_code, jurisdiction_code, broker_code, bot_id)
    """
    parts = str(get_bot_identity()).split("_")
    if len(parts) < 4:
        raise ValueError("Invalid BOT identity; expected 'ENTITY_JURISDICTION_BROKER_BOTID'")
    return parts[0], parts[1], parts[2], parts[3]


def get_ledger_db_path() -> str:
    """
    Resolver-derived DSN for the ledger database.
    """
    ec, jc, bc, bid = get_identity_tuple()
    return str(resolve_ledger_db_path(ec, jc, bc, bid))


# ---------------------------
# UTC helpers (no I/O)
# ---------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso(*, milliseconds: bool = True) -> str:
    if milliseconds:
        return now_utc().isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return now_utc().isoformat().replace("+00:00", "Z")


def to_utc(dt: Any) -> Optional[datetime]:
    """
    Convert str/datetime to timezone-aware UTC datetime. Invalid -> None.
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(dt, str):
        s = dt.strip()
        try:
            s = s.replace("Z", "+00:00") if "Z" in s else s
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def to_utc_iso(dt: Any, *, milliseconds: bool = True) -> Optional[str]:
    p = to_utc(dt)
    if p is None:
        return None
    if milliseconds:
        return p.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return p.isoformat().replace("+00:00", "Z")


# ---------------------------
# Connection configuration
# ---------------------------

def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """
    Configure connection-level pragmas for reliability and concurrency.
    """
    conn.execute("PRAGMA busy_timeout=5000;")     # ms
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")


def get_conn() -> sqlite3.Connection:
    """
    Open a configured SQLite connection to the ledger DB.
    Each call returns a fresh connection (safe for threaded usage patterns).
    """
    dsn = get_ledger_db_path()
    conn = sqlite3.connect(dsn, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Row objects by default
    _apply_pragmas(conn)
    return conn


@contextmanager
def tx_context() -> Iterator[sqlite3.Connection]:
    """
    Transaction context manager. Commits on success; rollbacks on error.
    Always closes the connection.
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dict_row_factory(cursor, row):
    """
    Optional dict row factory helper (not applied by default).
    """
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


__all__ = [
    "get_identity_tuple",
    "get_ledger_db_path",
    "get_conn",
    "tx_context",
    "dict_row_factory",
    "now_utc",
    "now_utc_iso",
    "to_utc",
    "to_utc_iso",
]
