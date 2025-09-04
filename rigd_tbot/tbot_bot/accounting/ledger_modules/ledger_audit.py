# tbot_bot/accounting/ledger_modules/ledger_audit.py

"""
Ledger audit-trail event logger.
Writes append-only rows into the `audit_trail` table defined by schema.sql.

Public API:
- append(event, **kwargs): structured writer aligned to AUDIT_TRAIL_FIELDS.

This version enforces a non-null event_type at code level (defaulting to
'UNSPECIFIED_EVENT'), sets SQLite connection pragmas (WAL, busy timeout),
and safely migrates older audit tables that are missing event_type or
contain NULL/blank values.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Set, List

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_fields import AUDIT_TRAIL_FIELDS

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

DEFAULT_EVENT_TYPE = "UNSPECIFIED_EVENT"


def _now_iso_utc() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def _resolve_db_path() -> str:
    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)


# ---------------- SQLite helpers / schema compatibility ----------------

def _open_conn(db_path: str) -> sqlite3.Connection:
    """
    Open a SQLite connection with safe defaults for concurrent web/API usage.
    """
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    except Exception:
        # Pragmas are best-effort; do not fail open.
        pass
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                (table,),
            ).fetchone()
        )
    except Exception:
        return False


def _audit_table_info(conn: sqlite3.Connection):
    """
    Returns list of PRAGMA table_info rows for audit_trail:
    (cid, name, type, notnull, dflt_value, pk)
    """
    try:
        return conn.execute("PRAGMA table_info(audit_trail)").fetchall()
    except Exception:
        return []


def _audit_existing_cols(conn: sqlite3.Connection) -> Set[str]:
    rows = _audit_table_info(conn)
    return {row[1] for row in rows} if rows else set()


def _audit_add_missing_columns(conn: sqlite3.Connection, have: Set[str]) -> None:
    """
    Add any missing columns we intend to write. For event_type we add with a
    DEFAULT to satisfy NOT NULL use-cases downstream.
    """
    # Ensure we only add columns that are known to our writer
    wanted: List[str] = list(AUDIT_TRAIL_FIELDS)
    if not wanted:
        return

    for col in wanted:
        if col in have:
            continue
        if col == "event_type":
            # Default so future inserts never violate NOT NULL expectations
            conn.execute(
                "ALTER TABLE audit_trail ADD COLUMN event_type TEXT DEFAULT ?",
                (DEFAULT_EVENT_TYPE,),
            )
        else:
            conn.execute(f"ALTER TABLE audit_trail ADD COLUMN {col} TEXT")


def _audit_backfill_null_event_type(conn: sqlite3.Connection) -> None:
    """
    If the column exists already, normalize NULL/blank → DEFAULT_EVENT_TYPE.
    """
    try:
        conn.execute(
            f"UPDATE audit_trail "
            f"SET event_type = ? "
            f"WHERE event_type IS NULL OR TRIM(event_type) = ''",
            (DEFAULT_EVENT_TYPE,),
        )
    except Exception:
        # Non-fatal; continue
        pass


def _audit_migrate_event_type(conn: sqlite3.Connection) -> None:
    """
    Safe, idempotent migration for event_type:
      * if column missing → add with DEFAULT 'UNSPECIFIED_EVENT'
      * backfill any NULL/blank values to DEFAULT
    """
    if not _table_exists(conn, "audit_trail"):
        return
    have = _audit_existing_cols(conn)
    if "event_type" not in have:
        # ALTER TABLE doesn't support parameter binding for DEFAULT literals cleanly.
        conn.execute(f"ALTER TABLE audit_trail ADD COLUMN event_type TEXT DEFAULT '{DEFAULT_EVENT_TYPE}'")
        conn.commit()
        have.add("event_type")
    _audit_backfill_null_event_type(conn)
    conn.commit()


def _audit_ensure_schema(conn: sqlite3.Connection) -> None:
    """
    One-time compatibility upgrade: migrate event_type first, then add any
    other missing columns our writer may emit.
    """
    if not _table_exists(conn, "audit_trail"):
        return
    _audit_migrate_event_type(conn)
    have = _audit_existing_cols(conn)
    _audit_add_missing_columns(conn, have)
    conn.commit()


# ------------------------------ Public API ------------------------------

def append(event: str, **kwargs) -> int:
    """
    Structured audit writer aligned to AUDIT_TRAIL_FIELDS.

    Required (enforced here):
      - event_type (from kwargs or 'event' or fallback to DEFAULT_EVENT_TYPE)

    Optional kwargs:
      - actor, related_id (or entry_id), group_id, trade_id
      - old_value, new_value (or before/after)
      - sync_run_id, source, notes, request_id, ip, user_agent
      - extra (dict | list | str | None)
      - old_account_code, new_account_code, reason  (packed into extra)

    Identity fields (entity_code, jurisdiction_code, broker_code, bot_id) are injected automatically.
    Returns the inserted row id (0 iff TEST_MODE_FLAG present).
    """
    if TEST_MODE_FLAG.exists():
        return 0

    # ---- Normalize required event_type (never allow NULL/blank) ----
    raw_event = kwargs.get("event_type") or event
    event_type = (raw_event or DEFAULT_EVENT_TYPE)
    if isinstance(event_type, str):
        event_type = event_type.strip() or DEFAULT_EVENT_TYPE
    else:
        event_type = DEFAULT_EVENT_TYPE

    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")

    # Normalize old/new values (accept before/after aliases)
    old_val = kwargs.get("old_value", kwargs.get("before"))
    new_val = kwargs.get("new_value", kwargs.get("after"))
    if isinstance(old_val, (dict, list)):
        old_val = json.dumps(old_val, ensure_ascii=False)
    if isinstance(new_val, (dict, list)):
        new_val = json.dumps(new_val, ensure_ascii=False)

    # Merge optional granular info into extra blob
    extra_blob = kwargs.get("extra")
    if isinstance(extra_blob, (dict, list)):
        extra_base = extra_blob
    elif isinstance(extra_blob, str) and extra_blob.strip():
        extra_base = extra_blob  # pass through string
    else:
        extra_base = {}

    if isinstance(extra_base, dict):
        for k in ("old_account_code", "new_account_code", "reason"):
            if k in kwargs and kwargs[k] is not None:
                extra_base[k] = kwargs[k]
        extra_value = json.dumps(extra_base, ensure_ascii=False)
    else:
        extra_value = extra_base  # already a string

    # Build a full record dict with canonical keys
    record = {
        "timestamp": _now_iso_utc(),  # keep using existing column naming in your DB
        "event_type": event_type,
        "action": kwargs.get("action") or event_type,
        "related_id": kwargs.get("related_id") or kwargs.get("entry_id"),
        "actor": kwargs.get("actor") or kwargs.get("user") or "system",
        "old_value": old_val,
        "new_value": new_val,
        # identity context
        "entity_code": entity_code,
        "jurisdiction_code": jurisdiction_code,
        "broker_code": broker_code,
        "bot_id": bot_id,
        # optional context
        "group_id": kwargs.get("group_id"),
        "trade_id": kwargs.get("trade_id"),
        "sync_run_id": kwargs.get("sync_run_id"),
        "source": kwargs.get("source"),
        "notes": kwargs.get("notes"),
        "request_id": kwargs.get("request_id"),
        "ip": kwargs.get("ip"),
        "user_agent": kwargs.get("user_agent"),
        "extra": extra_value,
    }

    # Ensure every known column has a key (None if not provided)
    for k in AUDIT_TRAIL_FIELDS:
        record.setdefault(k, None)

    db_path = _resolve_db_path()
    conn = _open_conn(db_path)
    try:
        _audit_ensure_schema(conn)

        # Discover actual table columns to build a compatible INSERT list
        info = _audit_table_info(conn)
        have_cols = [row[1] for row in info] if info else list(AUDIT_TRAIL_FIELDS)

        # Last defense: don't allow blank event_type if the column exists
        if "event_type" in have_cols and (record.get("event_type") is None or str(record.get("event_type")).strip() == ""):
            record["event_type"] = DEFAULT_EVENT_TYPE

        cols: List[str] = [c for c in AUDIT_TRAIL_FIELDS if c in have_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [record.get(c) for c in cols]

        cur = conn.execute(
            f"INSERT INTO audit_trail ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        try:
            conn.close()
        except Exception:
            pass
