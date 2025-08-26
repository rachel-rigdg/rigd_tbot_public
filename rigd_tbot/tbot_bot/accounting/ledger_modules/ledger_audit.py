# tbot_bot/accounting/ledger_modules/ledger_audit.py

"""
Ledger audit-trail event logger.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import AUDIT_TRAIL_FIELDS

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def log_audit_event(action, entry_id, user, before=None, after=None):
    """
    Write an audit event to audit_trail table for compliance tracking.
    """
    if TEST_MODE_FLAG.exists():
        return
    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    audit_entry = {
        "timestamp": now,
        "action": action,
        "related_id": entry_id,
        "actor": user,
        "old_value": json.dumps(before) if before else None,
        "new_value": json.dumps(after) if after else None
    }
    # Fill missing fields for schema compliance
    for k in AUDIT_TRAIL_FIELDS:
        if k not in audit_entry:
            audit_entry[k] = None
    columns = ", ".join(audit_entry.keys())
    placeholders = ", ".join("?" for _ in audit_entry)
    values = tuple(audit_entry.values())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO audit_trail ({columns}) VALUES ({placeholders})",
            values
        )
        conn.commit()
