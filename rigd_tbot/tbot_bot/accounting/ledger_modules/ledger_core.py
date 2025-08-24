# tbot_bot/accounting/ledger_modules/ledger_core.py

"""
Core ledger DB helpers (v048):
- get_conn(): open SQLite connection using resolver-derived DSN
- tx_context(): atomic transaction context (commit/rollback)
- row factory defaults, busy_timeout, WAL, foreign_keys=ON
- No direct Paths/decrypts; identity via utils_identity
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Tuple

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity


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


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """
    Configure connection-level pragmas for reliability and concurrency.
    """
    # Busy timeout for writer contention (ms)
    conn.execute("PRAGMA busy_timeout=5000;")
    # Enable FK enforcement
    conn.execute("PRAGMA foreign_keys=ON;")
    # WAL mode for concurrent readers
    conn.execute("PRAGMA journal_mode=WAL;")
    # Reasonable durability/perf trade-off
    conn.execute("PRAGMA synchronous=NORMAL;")


def get_conn() -> sqlite3.Connection:
    """
    Open a configured SQLite connection to the ledger DB.
    """
    dsn = get_ledger_db_path()
    conn = sqlite3.connect(dsn, detect_types=sqlite3.PARSE_DECLTYPES)
    # Row objects by default; callers may override to dict if desired
    conn.row_factory = sqlite3.Row
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
]
