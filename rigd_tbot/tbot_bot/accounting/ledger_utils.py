# tbot_bot/accounting/ledger_utils.py
# Ledger DB utilities: create OFX-compliant ledger db, schema validation, audit helpers.
# Handles ALL trade/cash event logging, querying, and audit logging.
# No COA/metadata structure logic—COA is managed in coa_utils.py only.

import os
import sqlite3
import json
from datetime import datetime
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_schema_path
from tbot_bot.support.utils_identity import get_bot_identity

BOT_ID = get_bot_identity()

CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

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
    Returns full ledger path for a logical account key (OFX-compliant).
    """
    return ACCOUNT_MAP.get(key, "")

def load_broker_code():
    """
    Loads broker code from encrypted bot_identity.json.enc
    """
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    return identity.split("_")[2]

def load_account_number():
    """
    Loads account number or code from encrypted acct_api.json.enc if present, else returns empty string.
    """
    try:
        key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "acct_api.key"
        enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "acct_api.json.enc"
        key = key_path.read_bytes()
        cipher = Fernet(key)
        plaintext = cipher.decrypt(enc_path.read_bytes())
        acct_api_data = json.loads(plaintext.decode("utf-8"))
        return acct_api_data.get("ACCOUNT_NUMBER", "") or acct_api_data.get("ACCOUNT_ID", "")
    except Exception:
        return ""

def validate_ledger_schema():
    """
    Checks that the ledger DB matches the required schema.
    Returns True if compliant, raises on missing schema.
    Skips validation if TEST_MODE active.
    """
    if TEST_MODE_FLAG.exists():
        # Skip schema validation during TEST_MODE
        return True

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
        # ============ SPEC FIELD CHECKS ===============
        cursor = conn.execute("PRAGMA table_info(trades)")
        required_fields = [
            "fitid", "tag", "leverage_multiplier", "account", "total_value", "datetime_utc"
        ]
        columns = [row[1] for row in cursor.fetchall()]
        for field in required_fields:
            if field not in columns:
                raise RuntimeError(f"Required field '{field}' missing in trades table schema")
    return True

def get_entry_by_id(entry_id):
    """
    Fetch a single ledger entry from trades table by id.
    """
    if TEST_MODE_FLAG.exists():
        # Skip ledger reads in TEST_MODE
        return None

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
    if TEST_MODE_FLAG.exists():
        # Skip audit logging in TEST_MODE
        return

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
            "INSERT INTO audit_trail (timestamp, action, related_id, actor, old_value, new_value) VALUES (?, ?, ?, ?, ?, ?)",
            (now, action, entry_id, user, json.dumps(before) if before else None, json.dumps(after) if after else None)
        )
        conn.commit()

def get_all_ledger_entries():
    """
    Fetch all ledger entries from trades table, returns list of dicts.
    """
    if TEST_MODE_FLAG.exists():
        # Skip ledger reads in TEST_MODE
        return []

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

def calculate_account_balances():
    """
    Dynamically calculate the sum of total_value grouped by account from the trades table.
    Returns a dict of {account: balance}.
    """
    if TEST_MODE_FLAG.exists():
        return {}

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
        cursor = conn.execute(
            "SELECT account, SUM(total_value) as balance FROM trades GROUP BY account"
        )
        balances = {row[0]: row[1] for row in cursor.fetchall()}
    return balances

def calculate_running_balances():
    """
    Returns list of dicts: each ledger entry with added field 'running_balance'.
    """
    if TEST_MODE_FLAG.exists():
        return []
    entries = get_all_ledger_entries()
    # Sort by datetime_utc ascending, id as tiebreaker
    entries.sort(key=lambda e: (e.get("datetime_utc", ""), e.get("id", 0)))
    running = 0.0
    out = []
    for entry in entries:
        val = float(entry.get("total_value") or 0)
        running += val
        entry["running_balance"] = round(running, 2)
        out.append(entry)
    return out

def get_coa_accounts():
    """
    Returns a list of (code, name) tuples for all COA accounts, sorted by name.
    Only for UI/account mapping; no transactional posting here.
    """
    if TEST_MODE_FLAG.exists():
        return []
    # Get identity for current ledger DB
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
        # Look for account_code and account_name in coa_accounts table
        cursor = conn.execute("SELECT json_extract(account_json, '$.code'), json_extract(account_json, '$.name') FROM coa_accounts")
        accounts = sorted([(row[0], row[1]) for row in cursor.fetchall() if row[0] and row[1]], key=lambda x: x[1])
    return accounts

def validate_double_entry():
    """
    Checks that for every transaction, debits and credits sum to zero (double-entry).
    Raises error if any imbalance found.
    """
    if TEST_MODE_FLAG.exists():
        return True
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
        cursor = conn.execute("SELECT fitid, SUM(total_value) FROM trades GROUP BY fitid")
        imbalances = [(fitid, total) for fitid, total in cursor.fetchall() if abs(total) > 1e-8]
        if imbalances:
            raise RuntimeError(f"Double-entry imbalance detected for fitids: {imbalances}")
    return True
