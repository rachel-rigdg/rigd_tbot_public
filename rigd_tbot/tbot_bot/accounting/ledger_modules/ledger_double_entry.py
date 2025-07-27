# tbot_bot/accounting/ledger_modules/ledger_double_entry.py

from tbot_bot.accounting.ledger_modules.ledger_account_map import get_account_path
from tbot_bot.accounting.coa_mapping_table import load_mapping_table, apply_mapping_rule
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import compliance_filter_ledger_entry
import sqlite3

def post_ledger_entries_double_entry(entries):
    bot_identity = get_identity_tuple()
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity
    mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)
    # Apply compliance filter to all entries before posting
    filtered_entries = [compliance_filter_ledger_entry(entry) for entry in entries if compliance_filter_ledger_entry(entry) is not None]
    return post_double_entry(filtered_entries, mapping_table)

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def _map_action(action):
    if not action or not isinstance(action, str):
        return "other"
    action_lower = action.lower()
    if action_lower in ("buy", "long"):
        return "long"
    if action_lower in ("sell", "short"):
        return "short"
    if action_lower in ("put", "call", "assignment", "exercise", "expire", "reorg", "inverse"):
        return action_lower
    return "other"

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
    if "trade_id" not in entry or not entry["trade_id"]:
        entry["trade_id"] = f"{broker_code}_{bot_id}_{hash(frozenset(entry.items()))}"
    if "total_value" not in entry or entry["total_value"] is None:
        entry["total_value"] = 0.0
    if "amount" not in entry or entry["amount"] is None:
        try:
            val = float(entry.get("total_value", 0.0))
        except Exception:
            val = 0.0
        side = entry.get("side", "")
        if isinstance(side, str) and side.lower() == "credit":
            entry["amount"] = -abs(val)
        else:
            entry["amount"] = abs(val)
    entry["action"] = _map_action(entry.get("action"))
    if "status" not in entry or not entry["status"]:
        entry["status"] = "ok"
    for k in TRADES_FIELDS:
        if k not in entry or entry[k] is None:
            entry[k] = None
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
            # Compliance filter is called in post_ledger_entries_double_entry
            debit_entry, credit_entry = apply_mapping_rule(entry, mapping_table)
            debit_entry = _add_required_fields(debit_entry, entity_code, jurisdiction_code, broker_code, bot_id)
            credit_entry = _add_required_fields(credit_entry, entity_code, jurisdiction_code, broker_code, bot_id)
            for side_entry in [debit_entry, credit_entry]:
                cur = conn.execute(
                    "SELECT 1 FROM trades WHERE trade_id = ? AND side = ?",
                    (side_entry.get("trade_id"), side_entry.get("side")),
                )
                if cur.fetchone():
                    continue
                columns = TRADES_FIELDS
                placeholders = ", ".join(["?"] * len(columns))
                conn.execute(
                    f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(side_entry.get(col) for col in columns)
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
