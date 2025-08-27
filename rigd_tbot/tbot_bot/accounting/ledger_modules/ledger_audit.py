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
    Structured audit writer. Fields are aligned to AUDIT_TRAIL_FIELDS / schema.sql.

    Required:
      - event (str)

    Optional kwargs (common):
      - actor, entry_id, group_id, trade_id
      - old_account_code, new_account_code, reason
      - sync_run_id, source, notes, request_id, ip, user_agent
      - extra (dict | list | str | None)

    Identity fields (entity_code, jurisdiction_code, broker_code, bot_id) are injected automatically.
    Returns the inserted row id.
    """
    if TEST_MODE_FLAG.exists():
        return 0

    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")

    extra = kwargs.get("extra")
    if isinstance(extra, (dict, list)):
        extra = json.dumps(extra, ensure_ascii=False)

    record = {
        # required core
        "ts_utc": _now_iso_utc(),
        "event": event,
        # identity
        "entity_code": entity_code,
        "jurisdiction_code": jurisdiction_code,
        "broker_code": broker_code,
        "bot_id": bot_id,
        # passthroughs
        "actor": kwargs.get("actor") or kwargs.get("user") or "system",
        "entry_id": kwargs.get("entry_id"),
        "group_id": kwargs.get("group_id"),
        "trade_id": kwargs.get("trade_id"),
        "old_account_code": kwargs.get("old_account_code"),
        "new_account_code": kwargs.get("new_account_code"),
        "reason": kwargs.get("reason"),
        "sync_run_id": kwargs.get("sync_run_id"),
        "source": kwargs.get("source"),
        "notes": kwargs.get("notes"),
        "request_id": kwargs.get("request_id"),
        "ip": kwargs.get("ip"),
        "user_agent": kwargs.get("user_agent"),
        "extra": extra,
    }

    # Ensure all required columns exist; fill missing with None
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
    Stores `before`/`after` blobs inside `extra`.
    """
    return append(
        event=action,
        entry_id=entry_id,
        actor=user,
        source="legacy",
        extra={"before": before, "after": after},
    )
