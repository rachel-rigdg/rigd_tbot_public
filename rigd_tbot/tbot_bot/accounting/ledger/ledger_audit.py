# tbot_bot/accounting/ledger/ledger_audit.py

import json
from datetime import datetime
from cryptography.fernet import Fernet
from pathlib import Path
import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

BOT_ID = get_bot_identity()
CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def log_audit_event(action, entry_id, user, before=None, after=None):
    if TEST_MODE_FLAG.exists():
        return
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_trail (timestamp, action, related_id, actor, old_value, new_value) VALUES (?, ?, ?, ?, ?, ?)",
            (now, action, entry_id, user, json.dumps(before) if before else None, json.dumps(after) if after else None)
        )
        conn.commit()
