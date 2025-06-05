# tbot_bot/accounting/init_ledger_db.py
# Bootstrap script: initializes a new bot ledger DB file using tbot_ledger_schema.sql (called only at provisioning/reset)

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import os
import sqlite3
import json
from cryptography.fernet import Fernet
from tbot_bot.support.path_resolver import (
    resolve_ledger_db_path,
)

def resolve_ledger_schema_path():
    """
    Returns the absolute path to tbot_ledger_schema.sql.
    """
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_schema.sql")

def init_ledger_db(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None):
    """
    Creates a new OFX-compliant ledger DB for this bot instance using the project schema.
    If arguments are None, use decrypted bot_identity.
    """
    if not all([entity_code, jurisdiction_code, broker_code, bot_id]):
        key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
        enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
        key = key_path.read_bytes()
        cipher = Fernet(key)
        plaintext = cipher.decrypt(enc_path.read_bytes())
        bot_identity_data = json.loads(plaintext.decode("utf-8"))
        identity = bot_identity_data.get("BOT_IDENTITY_STRING")
        entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")

    ledger_db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    schema_path = resolve_ledger_schema_path()
    if os.path.exists(ledger_db_path):
        raise FileExistsError(f"Ledger DB already exists: {ledger_db_path}")
    with open(schema_path, "r", encoding="utf-8") as schema_file:
        schema_sql = schema_file.read()
    os.makedirs(os.path.dirname(ledger_db_path), exist_ok=True)
    conn = sqlite3.connect(ledger_db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()

# CLI direct execution
if __name__ == "__main__":
    init_ledger_db()
