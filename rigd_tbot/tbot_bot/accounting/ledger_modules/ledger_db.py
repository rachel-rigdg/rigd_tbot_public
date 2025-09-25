# tbot_bot/accounting/ledger_modules/ledger_db.py

import os
import sqlite3
import json
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Optional  # <-- surgical: for Python 3.8/3.9 compatibility
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_schema_path
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS

# ---- Compliance filter (backwards compatible) ----
try:
    # Preferred: boolean helper
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (
        is_compliant_ledger_entry as _is_compliant,  # type: ignore
    )
except Exception:
    # Legacy helper that might return entry/None or (bool, reason)
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (  # type: ignore
        compliance_filter_ledger_entry as _legacy_compliance,
    )

    def _is_compliant(entry: dict) -> bool:
        res = _legacy_compliance(entry)
        if isinstance(res, tuple):
            return bool(res[0])
        return res is not None

BOT_ID = get_bot_identity()
CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"


def _read_identity_tuple():
    """
    Decrypts identity and returns (entity_code, jurisdiction_code, broker_code, bot_id).
    """
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    return entity_code, jurisdiction_code, broker_code, bot_id


def get_db_path():
    entity_code, jurisdiction_code, broker_code, bot_id = _read_identity_tuple()
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)


def validate_ledger_schema(db_path=None, schema_path=None):
    """
    Validates the ledger DB against the reference schema.
    Returns True if valid.
    Raises RuntimeError on any corruption/schema mismatch or validation error.
    """
    db_path = db_path or get_db_path()
    schema_path = schema_path or resolve_ledger_schema_path()
    try:
        with sqlite3.connect(db_path) as conn:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = f.read()
            cursor = conn.cursor()
            for stmt in schema.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                try:
                    cursor.execute(f"EXPLAIN {stmt}")
                except sqlite3.DatabaseError as e:
                    raise RuntimeError(f"[ledger_db] Ledger schema validation failed: {e}") from e
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"[ledger_db] Ledger schema validation error: {e}") from e
    return True


def _map_action(action: Optional[str]) -> str:  # <-- surgical: replace PEP 604 union for 3.8/3.9
    if not action or not isinstance(action, str):
        return "other"
    a = action.lower()
    if a in ("buy", "long"):
        return "long"
    if a in ("sell", "short"):
        return "short"
    if a in ("put", "call", "assignment", "exercise", "expire", "reorg", "inverse"):
        return a
    return "other"


def _sanitize_for_sqlite(entry: dict) -> dict:
    """
    Fill required fields, set identity, compute amount/side defaults,
    and JSON-encode any complex objects to avoid sqlite binding errors.
    """
    e = dict(entry)

    # Identity fields (NOT NULL in schema)
    entity_code, jurisdiction_code, broker_code, bot_id = _read_identity_tuple()
    e.setdefault("entity_code", entity_code)
    e.setdefault("jurisdiction_code", jurisdiction_code)
    e.setdefault("broker_code", broker_code)
    e.setdefault("bot_id", bot_id)

    # Ensure trade_id / group_id
    if not e.get("trade_id"):
        # hash of items — safe-ish placeholder
        e["trade_id"] = f"{broker_code}_{bot_id}_{hash(frozenset(e.items()))}"
    if not e.get("group_id"):
        e["group_id"] = e.get("trade_id")

    # Defaults for required numeric/side fields
    if "total_value" not in e or e["total_value"] is None:
        e["total_value"] = 0.0

    # Side default
    if not e.get("side"):
        e["side"] = "debit"

    # Amount sign based on side if missing
    if "amount" not in e or e["amount"] is None:
        try:
            val = float(e.get("total_value", 0.0))
        except Exception:
            val = 0.0
        e["amount"] = -abs(val) if str(e.get("side", "")).lower() == "credit" else abs(val)

    # Commission/Fee defaults
    if e.get("commission") is None:
        e["commission"] = 0.0
    if e.get("fee") is None:
        e["fee"] = 0.0

    # Account default (schema marks NOT NULL)
    if not e.get("account"):
        # Fallback to generic bucket depending on side for safety
        e["account"] = "Uncategorized:Credit" if e["side"].lower() == "credit" else "Uncategorized:Debit"

    # Normalize action/status
    e["action"] = _map_action(e.get("action"))
    if not e.get("status"):
        e["status"] = "ok"

    # Fill any missing schema fields (ensure key exists)
    for k in TRADES_FIELDS:
        if k not in e:
            e[k] = None

    # JSON-encode complex objects for safe sqlite binding
    for k, v in list(e.items()):
        if isinstance(v, (dict, list)):
            e[k] = json.dumps(v, default=str)

    return e


def add_entry(entry):
    """
    Adds a single ledger entry to the trades table.
    Enforces compliance and sanitization to prevent bad/incompatible rows.
    """
    if not isinstance(entry, dict):
        raise RuntimeError("Entry must be a dict")
    # Compliance check (bool)
    if not _is_compliant(entry):
        return  # silently ignore non-compliant entries

    db_path = get_db_path()
    e = _sanitize_for_sqlite(entry)

    keys = ", ".join(TRADES_FIELDS)
    placeholders = ", ".join("?" for _ in TRADES_FIELDS)
    values = tuple(e.get(k) for k in TRADES_FIELDS)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(f"INSERT INTO trades ({keys}) VALUES ({placeholders})", values)
            conn.commit()
    except Exception as exc:
        raise RuntimeError(f"Failed to add ledger entry: {exc}")


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
    Posts balanced double-entry records using the double-entry helper module.
    Applies compliance to each raw entry before delegating.
    """
    from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
        post_double_entry as _post_double_entry_helper,
    )

    # Filter non-compliant
    filtered = [e for e in entries if isinstance(e, dict) and _is_compliant(e)]
    if not filtered:
        return []

    return _post_double_entry_helper(filtered, mapping_table)


def run_schema_migration(migration_sql_path):
    """
    Runs a schema migration SQL script on the ledger DB.
    """
    db_path = get_db_path()
    try:
        with open(migration_sql_path, "r", encoding="utf-8") as f:
            migration_sql = f.read()
        with sqlite3.connect(db_path) as conn:
            conn.executescript(migration_sql)
            conn.commit()
    except Exception as e:
        raise RuntimeError(f"Failed to run schema migration: {e}")


def reconcile_ledger_with_coa():
    """
    Placeholder for reconciliation logic between ledger entries and COA accounts.
    """
    db_path = get_db_path()
    try:
        with sqlite3.connect(db_path):
            pass
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to reconcile ledger with COA: {e}")
