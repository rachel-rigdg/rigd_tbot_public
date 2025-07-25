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
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_trail (timestamp, action, related_id, actor, old_value, new_value) VALUES (?, ?, ?, ?, ?, ?)",
            (now, action, entry_id, user, json.dumps(before) if before else None, json.dumps(after) if after else None)
        )
        conn.commit()
