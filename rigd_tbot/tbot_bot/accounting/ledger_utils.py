# tbot_bot/accounting/ledger_utils.py
# Ledger DB utilities: create OFX-compliant ledger db, schema validation, audit helpers (no COA/metadata logic)

import os
import sqlite3
import json
from datetime import datetime
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_schema_path
from tbot_bot.support.utils_identity import get_bot_identity
BOT_ID = get_bot_identity()

ACCOUNT_MAP = {
    "cash":               "Assets:Brokerage Accounts – Equities:Cash",
    "equity":             "Assets:Brokerage Accounts – Equities",
    "gain":               "Income:Realized Gains",
    "fee":                "Expenses:Broker Fees",
    "slippage":           "Expenses:Slippage / Execution Losses",
    "failures":           "System Integrity:Failures & Rejected Orders",
    "infra":              "Expenses:Bot Infrastructure Costs",
    "float_ledger":       "Equity:Capital Float Ledger",
    "float_history":      "Equity:Daily Float Allocation History",
    "retained":           "Equity:Accumulated Profit",
    "opening":            "Equity:Opening Balance",
    "meta_trade":         "Logging / Execution References:Trade UUID",
    "meta_strategy":      "Logging / Execution References:Strategy Tag",
    "meta_recon":         "Logging / Execution References:Reconciliation Passed Flag",
    "meta_lock":          "System Integrity:Ledger Lock Flag (YES/NO)"
}

def get_account_path(key):
    """
    Returns full ledger path for a logical account key.
    """
    return ACCOUNT_MAP.get(key, "")

def validate_ledger_schema():
    """
    Checks that the ledger DB matches the required schema.
    Returns True if compliant, raises on missing schema.
    """
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")

    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    schema_path = resolve_ledger_schema_path()
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Ledger DB not found: {db_path}")
    with sqlite3.connect(db_path) as conn:
        for table in ("trades", "events", "audit_trail", "coa_metadata"):
            result = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'").fetchone()
            if not result:
                raise RuntimeError(f"Required table '{table}' missing in ledger DB: {db_path}")
    return True

def get_entry_by_id(entry_id):
    """
    Fetch a single ledger entry from trades table by id.
    """
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (entry_id,)).fetchone()
        return dict(zip([c[0] for c in conn.execute("PRAGMA table_info(trades)")], row)) if row else None

def log_audit_event(action, entry_id, user, before=None, after=None):
    """
    Write an audit event to audit_trail table for compliance tracking.
    """
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_trail (timestamp, action, entry_id, user, before, after) VALUES (?, ?, ?, ?, ?, ?)",
            (now, action, entry_id, user, json.dumps(before) if before else None, json.dumps(after) if after else None)
        )
        conn.commit()

def get_all_ledger_entries():
    """
    Fetch all ledger entries from trades table, returns list of dicts.
    """
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT * FROM trades")
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
