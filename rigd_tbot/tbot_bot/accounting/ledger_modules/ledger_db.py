# tbot_bot/accounting/ledger_modules/ledger_db.py

import os
import sqlite3
import json
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_schema_path
from tbot_bot.support.utils_identity import get_bot_identity

BOT_ID = get_bot_identity()
CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def get_db_path():
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)

def validate_ledger_schema(db_path=None, schema_path=None):
    """
    Validates the ledger DB against the reference schema. Returns True if valid, False if not.
    """
    db_path = db_path or get_db_path()
    schema_path = schema_path or resolve_ledger_schema_path()
    try:
        with sqlite3.connect(db_path) as conn:
            with open(schema_path, "r") as f:
                schema = f.read()
            cursor = conn.cursor()
            # Split schema into statements, skip empty
            for stmt in schema.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                try:
                    cursor.execute(f"EXPLAIN {stmt}")
                except sqlite3.DatabaseError as e:
                    return False
    except Exception:
        return False
    return True
