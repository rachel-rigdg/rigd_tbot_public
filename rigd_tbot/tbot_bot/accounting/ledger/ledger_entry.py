# tbot_bot/accounting/ledger/ledger_entry.py

import json
from cryptography.fernet import Fernet
from pathlib import Path
import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

BOT_ID = get_bot_identity()
CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def get_entry_by_id(entry_id):
    if TEST_MODE_FLAG.exists():
        return None
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (entry_id,)).fetchone()
        columns = [c[1] for c in conn.execute("PRAGMA table_info(trades)")]
        entry = dict(zip(columns, row)) if row else None
        if entry is not None:
            if "fee" in entry and "fee" not in entry:
                entry["fee"] = entry["fee"]
        return entry

def get_all_ledger_entries():
    if TEST_MODE_FLAG.exists():
        return []
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT * FROM trades")
        columns = [c[0] for c in cursor.description]
        entries = []
        for row in cursor.fetchall():
            entry = dict(zip(columns, row))
            if "fee" in entry and "fee" not in entry:
                entry["fee"] = entry["fee"]
            entries.append(entry)
        return entries
