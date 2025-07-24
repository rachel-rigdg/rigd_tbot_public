# tbot_bot/accounting/ledger/ledger_double_entry.py

import json
from cryptography.fernet import Fernet
from pathlib import Path
import sqlite3
from tbot_bot.accounting.coa_mapping_table import load_mapping_table, apply_mapping_rule
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

BOT_ID = get_bot_identity()
CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def validate_double_entry():
    if TEST_MODE_FLAG.exists():
        return True
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT trade_id, SUM(total_value) FROM trades GROUP BY trade_id")
        imbalances = [(trade_id, total) for trade_id, total in cursor.fetchall() if trade_id and abs(total) > 1e-8]
        if imbalances:
            raise RuntimeError(f"Double-entry imbalance detected for trade_ids: {imbalances}")
    return True

def post_double_entry(entries, mapping_table=None):
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
    inserted_ids = []
    if mapping_table is None:
        mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        for entry in entries:
            debit_entry, credit_entry = apply_mapping_rule(entry, mapping_table)
            columns = ", ".join(debit_entry.keys())
            placeholders = ", ".join(["?"] * len(debit_entry))
            conn.execute(
                f"INSERT INTO trades ({columns}) VALUES ({placeholders})",
                tuple(debit_entry.values())
            )
            columns = ", ".join(credit_entry.keys())
            placeholders = ", ".join(["?"] * len(credit_entry))
            conn.execute(
                f"INSERT INTO trades ({columns}) VALUES ({placeholders})",
                tuple(credit_entry.values())
            )
            conn.commit()
            inserted_ids.append((debit_entry.get("trade_id"), credit_entry.get("trade_id")))
    return inserted_ids
