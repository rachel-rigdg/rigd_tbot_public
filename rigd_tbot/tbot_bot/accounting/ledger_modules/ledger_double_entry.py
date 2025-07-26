# tbot_bot/accounting/ledger_modules/ledger_double_entry.py

from tbot_bot.accounting.ledger_modules.ledger_account_map import get_account_path
from tbot_bot.accounting.coa_mapping_table import load_mapping_table, apply_mapping_rule
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
import sqlite3

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def _add_required_fields(entry, entity_code, jurisdiction_code, broker_code, bot_id):
    entry = dict(entry)
    entry["entity_code"] = entity_code
    entry["jurisdiction_code"] = jurisdiction_code
    entry["broker_code"] = broker_code
    entry["bot_id"] = bot_id
    if "fee" not in entry or entry["fee"] is None:
        entry["fee"] = 0.0
    if "commission" not in entry or entry["commission"] is None:
        entry["commission"] = 0.0
    if "action" not in entry or entry["action"] is None:
        # Default safe fallback action, avoid NOT NULL constraint failure
        entry["action"] = "other"
    if "trade_id" not in entry or entry["trade_id"] is None:
        entry["trade_id"] = f"{broker_code}_{bot_id}_{hash(frozenset(entry.items()))}"
    if "total_value" not in entry or entry["total_value"] is None:
        entry["total_value"] = 0.0
    if "amount" not in entry or entry["amount"] is None:
        try:
            val = float(entry.get("total_value", 0.0))
        except Exception:
            val = 0.0
        side = entry.get("side", "").lower()
        if side == "credit":
            entry["amount"] = -abs(val)
        else:
            entry["amount"] = abs(val)
    if "status" not in entry or entry["status"] is None:
        entry["status"] = "ok"
    return entry

def post_double_entry(entries, mapping_table=None):
    bot_identity = get_identity_tuple()
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    inserted_ids = []
    if mapping_table is None:
        mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        for entry in entries:
            debit_entry, credit_entry = apply_mapping_rule(entry, mapping_table)
            debit_entry = _add_required_fields(debit_entry, entity_code, jurisdiction_code, broker_code, bot_id)
            credit_entry = _add_required_fields(credit_entry, entity_code, jurisdiction_code, broker_code, bot_id)
            columns = TRADES_FIELDS
            placeholders = ", ".join(["?"] * len(columns))
            conn.execute(
                f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(debit_entry.get(col) for col in columns)
            )
            conn.execute(
                f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(credit_entry.get(col) for col in columns)
            )
            conn.commit()
            inserted_ids.append((debit_entry.get("trade_id"), credit_entry.get("trade_id")))
    return inserted_ids

def validate_double_entry():
    bot_identity = get_identity_tuple()
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT trade_id, SUM(total_value) FROM trades GROUP BY trade_id")
        imbalances = [(trade_id, total) for trade_id, total in cursor.fetchall() if trade_id and abs(total) > 1e-8]
        if imbalances:
            raise RuntimeError(f"Double-entry imbalance detected for trade_ids: {imbalances}")
    return True
