# tbot_bot/accounting/ledger_modules/ledger_audit.py

"""
Ledger audit-trail event logger.
Writes append-only rows into the `audit_trail` table defined by schema.sql.

Public API:
- append(event, **kwargs): structured writer aligned to AUDIT_TRAIL_FIELDS.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_fields import AUDIT_TRAIL_FIELDS

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"


def _now_iso_utc() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def _resolve_db_path() -> str:
    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)


# -------- Schema helpers (safe on SQLite) --------

def _audit_table_info(conn: sqlite3.Connection):
    """
    Returns list of PRAGMA table_info rows for audit_trail:
    (cid, name, type, notnull, dflt_value, pk)
    """
    try:
        return conn.execute("PRAGMA table_info(audit_trail)").fetchall()
    except Exception:
        return []


def _audit_existing_cols(conn: sqlite3.Connection) -> set:
    rows = _audit_table_info(conn)
    return {row[1] for row in rows} if rows else set()


def _audit_ensure_schema(conn: sqlite3.Connection) -> None:
    """
    One-time upgrade: add any missing columns we intend to write.
    Uses AUDIT_TRAIL_FIELDS; columns are added as TEXT with NULL default
    (fine for SQLite and non-destructive).
    """
    have = _audit_existing_cols(conn)
    if not have:
        return
    for col in AUDIT_TRAIL_FIELDS:
        if col not in have:
            conn.execute(f"ALTER TABLE audit_trail ADD COLUMN {col} TEXT")


def append(event: str, **kwargs) -> int:
    """
    Structured audit writer aligned to AUDIT_TRAIL_FIELDS.

    Required:
      - event (str) or event_type in kwargs → persisted in 'event_type' column (NOT NULL)

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

    # ---- Validate required event_type (derive from event if needed) ----
    event_type = (kwargs.get("event_type") or event or "").strip()
    if not event_type:
        # Fail fast with a clear message rather than sending NULL to the DB
        raise ValueError("[ledger_audit.append] 'event_type' is required and must be non-empty.")

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
        # leave as-is string
        extra_base = extra_blob
    else:
        extra_base = {}

    if isinstance(extra_base, dict):
        for k in ("old_account_code", "new_account_code", "reason"):
            if k in kwargs and kwargs[k] is not None:
                extra_base[k] = kwargs[k]
        extra_value = json.dumps(extra_base, ensure_ascii=False)
    else:
        extra_value = extra_base  # string passthrough

    # Build a full record dict with canonical keys
    record = {
        "timestamp": _now_iso_utc(),
        # Ensure both modern and legacy-named columns are populated consistently
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

    # Ensure every known column has a value (None if not provided)
    for k in AUDIT_TRAIL_FIELDS:
        record.setdefault(k, None)

    db_path = _resolve_db_path()
    with sqlite3.connect(db_path) as conn:
        # Ensure schema is at least as new as our writer
        _audit_ensure_schema(conn)

        # Use ACTUAL table columns; ALWAYS include event_type if present
        have_cols = list(_audit_existing_cols(conn))
        if not have_cols:
            have_cols = AUDIT_TRAIL_FIELDS[:]  # last-resort fallback

        # Desired order: event_type first, then the canonical list (without duplicates)
        desired = ["event_type"] + [c for c in AUDIT_TRAIL_FIELDS if c != "event_type"]
        cols = [c for c in desired if c in have_cols]

        # Belt & suspenders: if the table has event_type, it must be provided and non-empty
        if "event_type" in cols and not (record.get("event_type") or "").strip():
            raise ValueError("[ledger_audit.append] 'event_type' is required by the current schema.")

        placeholders = ", ".join(["?"] * len(cols))
        vals = [record.get(c) for c in cols]

        cur = conn.execute(
            f"INSERT INTO audit_trail ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        conn.commit()
        return int(cur.lastrowid)
