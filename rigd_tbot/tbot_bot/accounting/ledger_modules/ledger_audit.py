# tbot_bot/accounting/ledger_modules/ledger_audit.py

"""
Ledger audit-trail event logger.
Writes append-only rows into the `audit_trail` table defined by schema.sql.

Public API:
- append(event, **kwargs): structured writer aligned to AUDIT_TRAIL_FIELDS.
- log_audit_event(action, entry_id, user, before=None, after=None): legacy shim.
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


def append(event: str, **kwargs) -> int:
    """
    Structured audit writer aligned to AUDIT_TRAIL_FIELDS.

    Required:
      - event (str) → stored in 'action'

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
        extra = json.dumps(extra_base, ensure_ascii=False)
    else:
        extra = extra_base  # string passthrough

    # Build record with canonical column names
    record = {
        "timestamp": _now_iso_utc(),
        "action": event,
        "related_id": kwargs.get("related_id") or kwargs.get("entry_id"),
        "actor": kwargs.get("actor") or kwargs.get("user") or "system",
        "old_value": old_val,
        "new_value": new_val,
        # optional context
        "entity_code": entity_code,
        "jurisdiction_code": jurisdiction_code,
        "broker_code": broker_code,
        "bot_id": bot_id,
        "group_id": kwargs.get("group_id"),
        "trade_id": kwargs.get("trade_id"),
        "sync_run_id": kwargs.get("sync_run_id"),
        "source": kwargs.get("source"),
        "notes": kwargs.get("notes"),
        "request_id": kwargs.get("request_id"),
        "ip": kwargs.get("ip"),
        "user_agent": kwargs.get("user_agent"),
        "extra": extra,
    }

    # Fill any missing fields required by the schema with None
    for k in AUDIT_TRAIL_FIELDS:
        record.setdefault(k, None)

    cols = ", ".join(AUDIT_TRAIL_FIELDS)
    placeholders = ", ".join(["?"] * len(AUDIT_TRAIL_FIELDS))
    vals = [record[k] for k in AUDIT_TRAIL_FIELDS]

    db_path = _resolve_db_path()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(f"INSERT INTO audit_trail ({cols}) VALUES ({placeholders})", vals)
        conn.commit()
        return int(cur.lastrowid)


# -------- Legacy shim (backward compatible) --------
def log_audit_event(action: str, entry_id, user, before=None, after=None) -> int:
    """
    Legacy signature used by older code. Maps to structured append().
    """
    return append(
        event=action,
        related_id=entry_id,
        actor=user,
        old_value=before,
        new_value=after,
        source="legacy",
    )
