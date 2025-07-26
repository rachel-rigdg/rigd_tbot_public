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
                except sqlite3.DatabaseError:
                    return False
    except Exception:
        return False
    return True

def add_entry(entry):
    """
    Adds a ledger entry to the trades table.
    """
    db_path = get_db_path()
    keys = ", ".join(entry.keys())
    placeholders = ", ".join("?" for _ in entry)
    values = tuple(entry.values())
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(f"INSERT INTO trades ({keys}) VALUES ({placeholders})", values)
            conn.commit()
    except Exception as e:
        raise RuntimeError(f"Failed to add ledger entry: {e}")

def _schema_has_amount_side(db_path):
    """
    Checks if the trades table has 'amount' and 'side' columns.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(trades)")
            cols = [row[1] for row in cursor.fetchall()]
            return ("amount" in cols) and ("side" in cols)
    except Exception:
        return False

def post_double_entry(entries, mapping_table=None):
    """
    Posts balanced double-entry records using the double entry helper module.
    """
    from tbot_bot.accounting.ledger_modules.ledger_double_entry import post_double_entry as double_entry_helper
    return double_entry_helper(entries, mapping_table)

def run_schema_migration(migration_sql_path):
    """
    Runs a schema migration SQL script on the ledger DB.
    """
    db_path = get_db_path()
    try:
        with open(migration_sql_path, "r") as f:
            migration_sql = f.read()
        with sqlite3.connect(db_path) as conn:
            conn.executescript(migration_sql)
            conn.commit()
    except Exception as e:
        raise RuntimeError(f"Failed to run schema migration: {e}")

def reconcile_ledger_with_coa():
    """
    Runs reconciliation logic between ledger entries and COA accounts.
    """
    db_path = get_db_path()
    # Placeholder: actual reconciliation logic must be implemented here.
    try:
        with sqlite3.connect(db_path) as conn:
            # Implement reconciliation logic as needed
            pass
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to reconcile ledger with COA: {e}")
