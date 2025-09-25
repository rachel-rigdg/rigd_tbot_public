# tbot_bot/accounting/ledger_modules/ledger_audit.py

"""
Ledger audit-trail event logger.
Writes append-only rows into the `audit_trail` table defined by schema.sql.

Public API:
- append(event, **kwargs): structured writer aligned to AUDIT_TRAIL_FIELDS.

This version:
- Guarantees a non-null, non-blank event_type (defaults to 'UNSPECIFIED_EVENT').
- Fills an 'action' field (falls back to event_type) to satisfy NOT NULL schemas.
- Opens SQLite with WAL + busy timeout pragmas for concurrent web/API usage.
- Performs idempotent, race-safe, backward-compatible schema migrations:
  * Adds missing columns only if absent; ignores duplicate-column races.
  * Ensures event_type exists and backfills NULL/blank values.
  * Writes extra/payload JSON into whichever JSON-ish column the table provides.
  * Supports both 'timestamp' and 'created_at' time columns.

Notes:
- We intentionally do not auto-create the audit_trail table; schema.sql should do that.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Set, List, Dict, Any, Optional

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_fields import AUDIT_TRAIL_FIELDS

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

DEFAULT_EVENT_TYPE = "UNSPECIFIED_EVENT"


# -------------------------- time/db helpers --------------------------

def _now_iso_utc() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def _resolve_db_path() -> str:
    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)


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


# ---------------------- schema inspection/migration ----------------------

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


def _is_duplicate_column_error(err: Exception) -> bool:
    s = str(err).lower()
    return "duplicate column name" in s or "already exists" in s


def _sql_quote_literal(val: str) -> str:
    """Minimal SQL literal escaper for single quotes."""
    return val.replace("'", "''")


def _audit_add_missing_columns(conn: sqlite3.Connection, have: Set[str]) -> None:
    """
    Add any missing columns we intend to write. For event_type we add with a
    DEFAULT to satisfy NOT NULL use-cases downstream.

    This is race-safe: duplicate-column ALTER errors are swallowed.
    """
    # Ensure we only add columns that are known to our writer
    wanted: List[str] = list(AUDIT_TRAIL_FIELDS or [])
    if not wanted:
        return

    for col in wanted:
        if col in have:
            continue
        try:
            if col == "event_type":
                # SQLite doesn't parameter-bind DEFAULT literals on ALTER TABLE.
                lit = _sql_quote_literal(DEFAULT_EVENT_TYPE)
                conn.execute(f"ALTER TABLE audit_trail ADD COLUMN event_type TEXT DEFAULT '{lit}'")
            else:
                conn.execute(f"ALTER TABLE audit_trail ADD COLUMN {col} TEXT")
            have.add(col)  # update our local snapshot
        except sqlite3.OperationalError as e:
            if _is_duplicate_column_error(e):
                have.add(col)
                continue
            # Swallow other ALTER hiccups to avoid breaking UI paths
            continue


def _audit_backfill_null_event_type(conn: sqlite3.Connection) -> None:
    """
    If the column exists already, normalize NULL/blank → DEFAULT_EVENT_TYPE.
    """
    try:
        conn.execute(
            "UPDATE audit_trail SET event_type = ? WHERE event_type IS NULL OR TRIM(event_type) = ''",
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
        try:
            lit = _sql_quote_literal(DEFAULT_EVENT_TYPE)
            conn.execute(f"ALTER TABLE audit_trail ADD COLUMN event_type TEXT DEFAULT '{lit}'")
            have.add("event_type")
        except sqlite3.OperationalError as e:
            if not _is_duplicate_column_error(e):
                # Ignore; migration is best-effort
                pass
            else:
                have.add("event_type")
    _audit_backfill_null_event_type(conn)


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
    try:
        conn.commit()
    except Exception:
        pass


# ------------------------------ Public API ------------------------------

def append(event: str, **kwargs) -> int:
    """
    Structured audit writer aligned to AUDIT_TRAIL_FIELDS.

    Required (enforced here):
      - event_type (from kwargs or positional 'event' or fallback to DEFAULT_EVENT_TYPE)

    Optional kwargs:
      - actor, related_id (or entry_id), group_id, trade_id
      - old_value, new_value (or before/after)
      - sync_run_id, source, notes, request_id, ip, user_agent, action
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
        extra_base: Any = extra_blob
    elif isinstance(extra_blob, str) and extra_blob.strip():
        extra_base = extra_blob  # pass through string
    else:
        extra_base = {}

    if isinstance(extra_base, dict):
        for k in ("old_account_code", "new_account_code", "reason"):
            if k in kwargs and kwargs[k] is not None:
                extra_base[k] = kwargs[k]
        extra_json = json.dumps(extra_base, ensure_ascii=False)
    else:
        extra_json = extra_base  # already a string

    # Build a full record dict with canonical keys; some schemas use different names.
    now_iso = _now_iso_utc()
    record: Dict[str, Any] = {
        # Time (support both names; we'll write whatever exists)
        "timestamp": now_iso,
        "created_at": now_iso,

        # Required event identity
        "event_type": event_type,
        "action": (kwargs.get("action") or event_type),  # satisfy NOT NULL action schemas

        # Linkage & actor
        "related_id": kwargs.get("related_id") or kwargs.get("entry_id"),
        "actor": kwargs.get("actor") or kwargs.get("user") or "system",

        # Values
        "old_value": old_val,
        "new_value": new_val,

        # Identity context
        "entity_code": entity_code,
        "jurisdiction_code": jurisdiction_code,
        "broker_code": broker_code,
        "bot_id": bot_id,

        # Optional context
        "group_id": kwargs.get("group_id"),
        "trade_id": kwargs.get("trade_id"),
        "sync_run_id": kwargs.get("sync_run_id"),
        "source": kwargs.get("source"),
        "notes": kwargs.get("notes"),
        "request_id": kwargs.get("request_id"),
        "ip": kwargs.get("ip"),
        "user_agent": kwargs.get("user_agent"),

        # JSON-ish payload candidates (we'll select the available column)
        "extra": extra_json,
        "extra_json": extra_json,
        "payload": extra_json,
        "payload_json": extra_json,
        "metadata": extra_json,
        "meta_json": extra_json,
    }

    # Ensure every known column from AUDIT_TRAIL_FIELDS has a key (None if not provided)
    for k in (AUDIT_TRAIL_FIELDS or []):
        record.setdefault(k, None)

    db_path = _resolve_db_path()
    conn = _open_conn(db_path)
    try:
        _audit_ensure_schema(conn)

        # Discover actual table columns to build a compatible INSERT list
        info = _audit_table_info(conn)
        have_cols = [row[1] for row in info] if info else list(AUDIT_TRAIL_FIELDS or [])

        # Last defense: don't allow blank event_type or action if columns exist
        if "event_type" in have_cols and (record.get("event_type") is None or str(record.get("event_type")).strip() == ""):
            record["event_type"] = DEFAULT_EVENT_TYPE
        if "action" in have_cols and (record.get("action") is None or str(record.get("action")).strip() == ""):
            record["action"] = record.get("event_type", DEFAULT_EVENT_TYPE)

        # Prefer whichever time column the table actually has
        if "timestamp" in have_cols:
            pass  # record['timestamp'] already set
        elif "created_at" in have_cols:
            pass  # record['created_at'] already set

        # Prefer the JSON-ish column the table actually has
        json_col_priority = ["extra", "extra_json", "payload", "payload_json", "metadata", "meta_json"]
        chosen_json_col: Optional[str] = None
        for jc in json_col_priority:
            if jc in have_cols:
                chosen_json_col = jc
                break
        if chosen_json_col:
            # Make sure only the chosen json column is kept (others may be absent in schema)
            for jc in json_col_priority:
                if jc != chosen_json_col:
                    record.pop(jc, None)

        # Build INSERT using intersection of known fields and existing columns
        cols: List[str] = [c for c in (AUDIT_TRAIL_FIELDS or []) if c in have_cols and c in record]
        # Ensure we also include chosen time/json columns if they are not in AUDIT_TRAIL_FIELDS
        for extra_col in ("timestamp", "created_at"):
            if extra_col in have_cols and extra_col not in cols and extra_col in record:
                cols.append(extra_col)
        if chosen_json_col and chosen_json_col not in cols:
            cols.append(chosen_json_col)

        placeholders = ", ".join(["?"] * len(cols))
        vals = [record.get(c) for c in cols]

        cur = conn.execute(
            f"INSERT INTO audit_trail ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        try:
            conn.commit()
        except Exception:
            pass
        return int(cur.lastrowid)
    finally:
        try:
            conn.close()
        except Exception:
            pass
