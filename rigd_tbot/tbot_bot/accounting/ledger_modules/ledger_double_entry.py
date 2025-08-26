# tbot_bot/accounting/ledger_modules/ledger_double_entry.py

from typing import Optional
from tbot_bot.accounting.ledger_modules.ledger_account_map import get_account_path  # kept for downstream imports
from tbot_bot.accounting.coa_mapping_table import load_mapping_table, apply_mapping_rule
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
import sqlite3
import json

# ---- Compliance filter (backwards-compatible import) ----
try:
    # New-style boolean function
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (
        is_compliant_ledger_entry as _is_compliant_ledger_entry,  # type: ignore
    )
except Exception:
    # Legacy function returning entry/None or (bool, reason)
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (  # type: ignore
        compliance_filter_ledger_entry as _legacy_filter,
    )

    def _is_compliant_ledger_entry(entry: dict) -> bool:
        res = _legacy_filter(entry)
        if isinstance(res, tuple):
            return bool(res[0])
        return res is not None


def post_ledger_entries_double_entry(entries):
    """
    Public entry point used by hooks and other modules.
    Loads mapping table from identity and posts compliant entries.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)
    # Apply compliance filter to all entries before posting
    filtered_entries = [e for e in entries if _is_compliant_ledger_entry(e)]
    return post_double_entry(filtered_entries, mapping_table)


def get_identity_tuple():
    identity = load_bot_identity() or ""
    parts = identity.split("_")
    # defensive padding to length 4
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])


def _map_action(action: Optional[str]) -> str:
    # Map broker actions to ledger schema actions
    if not action or not isinstance(action, str):
        return "other"
    action_lower = action.lower()
    if action_lower in ("buy", "long"):
        return "long"
    if action_lower in ("sell", "short"):
        return "short"
    if action_lower in ("put", "call", "assignment", "exercise", "expire", "reorg", "inverse"):
        return action_lower
    # Default fallback
    return "other"


def _add_required_fields(entry, entity_code, jurisdiction_code, broker_code, bot_id):
    """
    Ensure mandatory columns exist, coerce numerics, and JSON-encode complex values
    so SQLite bindings never see dict/list objects.
    """
    entry = dict(entry)

    # Identity context
    entry["entity_code"] = entity_code
    entry["jurisdiction_code"] = jurisdiction_code
    entry["broker_code"] = broker_code
    entry["bot_id"] = bot_id

    # Defaults
    entry["fee"] = 0.0 if entry.get("fee") is None else entry.get("fee")
    entry["commission"] = 0.0 if entry.get("commission") is None else entry.get("commission")

    # Ensure trade_id / group_id exist
    if not entry.get("trade_id"):
        entry["trade_id"] = f"{broker_code}_{bot_id}_{hash(frozenset(entry.items()))}"
    if not entry.get("group_id"):
        entry["group_id"] = entry.get("trade_id")

    if "total_value" not in entry or entry["total_value"] is None:
        entry["total_value"] = 0.0

    # Compute amount sign from side when missing
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

    # Normalize action and status
    entry["action"] = _map_action(entry.get("action"))
    if "status" not in entry or not entry["status"]:
        entry["status"] = "ok"

    # Fill any missing schema fields with None
    for k in TRADES_FIELDS:
        if k not in entry or entry[k] is None:
            entry[k] = None

    # --- CRITICAL SANITATION: JSON-encode complex values so sqlite bindings are safe ---
    for k, v in list(entry.items()):
        if isinstance(v, (dict, list)):
            entry[k] = json.dumps(v, default=str)

    return entry


def post_double_entry(entries, mapping_table=None):
    """
    Low-level poster: maps each raw entry to debit/credit legs and writes both.
    Assumes entries have already passed compliance when called via the public wrapper.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    inserted_ids = []
    if mapping_table is None:
        mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)

    with sqlite3.connect(db_path) as conn:
        for entry in entries:
            debit_entry, credit_entry = apply_mapping_rule(entry, mapping_table)

            debit_entry = _add_required_fields(debit_entry, entity_code, jurisdiction_code, broker_code, bot_id)
            credit_entry = _add_required_fields(credit_entry, entity_code, jurisdiction_code, broker_code, bot_id)

            # Deduplication logic: (trade_id, side) unique constraint
            for side_entry in (debit_entry, credit_entry):
                cur = conn.execute(
                    "SELECT 1 FROM trades WHERE trade_id = ? AND side = ?",
                    (side_entry.get("trade_id"), side_entry.get("side")),
                )
                if cur.fetchone():
                    continue  # Skip duplicate

                columns = TRADES_FIELDS
                placeholders = ", ".join(["?"] * len(columns))
                conn.execute(
                    f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(side_entry.get(col) for col in columns),
                )

            conn.commit()
            inserted_ids.append((debit_entry.get("trade_id"), credit_entry.get("trade_id")))
    return inserted_ids


def validate_double_entry():
    """
    Validates that each trade_id sums to zero across its legs.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT trade_id, SUM(total_value) FROM trades GROUP BY trade_id")
        imbalances = [(trade_id, total) for trade_id, total in cursor.fetchall() if trade_id and abs(total) > 1e-8]
        if imbalances:
            raise RuntimeError(f"Double-entry imbalance detected for trade_ids: {imbalances}")
    return True
