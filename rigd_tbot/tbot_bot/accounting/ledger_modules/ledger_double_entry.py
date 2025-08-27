# tbot_bot/accounting/ledger_modules/ledger_double_entry.py

from typing import Optional, Tuple, List, Dict, Any
from tbot_bot.accounting.ledger_modules.ledger_account_map import get_account_path  # kept for downstream imports
from tbot_bot.accounting.coa_mapping_table import load_mapping_table, apply_mapping_rule
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
import sqlite3
import json


# ---- Compliance filter (backwards-compatible import) ----
try:
    # Preferred new-style boolean function
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


# ---------------------------
# Constants / Helpers
# ---------------------------

SUSPENSE = "3999_SUSPENSE"
PNL = "5000_TRADING_PNL"


def get_identity_tuple() -> Tuple[str, str, str, str]:
    identity = load_bot_identity() or ""
    parts = identity.split("_")
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])  # (entity_code, jurisdiction_code, broker_code, bot_id)


def _as_float(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, str) and x.strip() in ("", "None"):
            return default
        return float(x)
    except Exception:
        return default


def _map_action(action: Optional[str]) -> str:
    """Map broker/raw actions to normalized ledger schema actions."""
    if not action or not isinstance(action, str):
        return "other"
    a = action.strip().lower()
    if a in ("buy", "long"):
        return "long"
    if a in ("sell", "short"):
        return "short"
    if a in ("put", "call", "assignment", "exercise", "expire", "reorg", "inverse"):
        return a
    return "other"


def _jsonify_if_needed(v):
    """SQLite bindings must not see dict/list; encode to JSON string."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def _ensure_json_fields(entry: dict) -> None:
    """
    Ensure json-bearing columns exist and are strings, not dicts.
    Keep keys consistent with TRADES_FIELDS: json_metadata, raw_broker_json.
    """
    if "json_metadata" not in entry or entry["json_metadata"] is None:
        entry["json_metadata"] = "{}"
    if "raw_broker_json" not in entry or entry["raw_broker_json"] is None:
        entry["raw_broker_json"] = "{}"


def _add_required_fields(entry: dict,
                         entity_code: str,
                         jurisdiction_code: str,
                         broker_code: str,
                         bot_id: str) -> dict:
    """
    Ensure mandatory columns exist, coerce numerics, normalize actions, set IDs,
    and JSON-encode complex values so SQLite bindings never see dict/list objects.
    """
    e = dict(entry or {})

    # Identity context (always present)
    e["entity_code"] = entity_code
    e["jurisdiction_code"] = jurisdiction_code
    e["broker_code"] = broker_code
    e["bot_id"] = bot_id

    # Normalize action/status
    e["action"] = _map_action(e.get("action"))
    if not e.get("status"):
        e["status"] = "ok"

    # Numerics (don’t throw)
    e["fee"] = _as_float(e.get("fee"), 0.0)
    e["commission"] = _as_float(e.get("commission"), 0.0)
    e["price"] = _as_float(e.get("price"), e.get("price") or 0.0)
    e["quantity"] = _as_float(e.get("quantity"), e.get("quantity") or 0.0)

    # Total value default
    if "total_value" not in e or e["total_value"] is None:
        e["total_value"] = _as_float(e.get("total_value"), 0.0)

    # Compute amount sign from side when missing (credit ⇒ negative; debit ⇒ positive)
    if e.get("amount") is None:
        val = _as_float(e.get("total_value"), 0.0)
        side = (e.get("side") or "").strip().lower()
        e["amount"] = -abs(val) if side == "credit" else abs(val)

    # Ensure IDs (make hashing safe if dict/list present)
    if not e.get("trade_id"):
        try:
            h = hash(frozenset(e.items()))
        except TypeError:
            h = hash(repr(sorted(e.items())))
        e["trade_id"] = f"{broker_code}_{bot_id}_{abs(h)}"
    if not e.get("group_id"):
        e["group_id"] = e.get("trade_id")

    # JSON-bearing fields
    _ensure_json_fields(e)

    # Fill any missing schema fields with None; then sanitize complex types
    for k in TRADES_FIELDS:
        if k not in e:
            e[k] = None

    # Sanitize: JSON-encode complex types
    for k, v in list(e.items()):
        e[k] = _jsonify_if_needed(v)

    return e


def _fallback_unmapped_legs(entry_in: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    When no mapping rule exists, route to Suspense vs P&L so rows are not dropped.
    Ensures zero-sum across legs.
    """
    e = dict(entry_in or {})
    val = _as_float(e.get("total_value"), 0.0)
    if val >= 0:
        debit = {**e, "side": "debit",  "account": SUSPENSE, "total_value": abs(val),  "amount":  abs(val)}
        credit= {**e, "side": "credit", "account": PNL,      "total_value": -abs(val), "amount": -abs(val)}
    else:
        debit = {**e, "side": "debit",  "account": PNL,      "total_value": abs(val),  "amount":  abs(val)}
        credit= {**e, "side": "credit", "account": SUSPENSE, "total_value": -abs(val), "amount": -abs(val)}
    return debit, credit


# ---------------------------
# Public API
# ---------------------------

def post_ledger_entries_double_entry(entries: List[dict]):
    """
    Public entry point used by hooks and other modules.
    Loads mapping table from identity and posts compliant entries.
    Returns list of (debit_trade_id, credit_trade_id) pairs that were (attempted to be) inserted.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)

    # Apply compliance filter before posting
    filtered_entries = [e for e in (entries or []) if _is_compliant_ledger_entry(e)]
    return post_double_entry(filtered_entries, mapping_table)


def post_double_entry(entries: List[dict], mapping_table=None):
    """
    Low-level poster: maps each raw entry to debit/credit legs and writes both.
    Assumes entries have already passed compliance when called via the public wrapper.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    inserted_ids: List[Tuple[Optional[str], Optional[str]]] = []

    if mapping_table is None:
        mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)

    with sqlite3.connect(db_path) as conn:
        for entry in entries or []:
            # Try rule-based mapping; fallback to Suspense/PNL if mapping missing/invalid
            try:
                debit_entry, credit_entry = apply_mapping_rule(entry, mapping_table)
                if (not debit_entry or not credit_entry
                        or not debit_entry.get("account") or not credit_entry.get("account")):
                    raise ValueError("unmapped_rule")
            except Exception:
                debit_entry, credit_entry = _fallback_unmapped_legs(entry)

            # Normalize/sanitize payloads for DB
            debit_entry = _add_required_fields(debit_entry, entity_code, jurisdiction_code, broker_code, bot_id)
            credit_entry = _add_required_fields(credit_entry, entity_code, jurisdiction_code, broker_code, bot_id)

            # Dedupe guard: (trade_id, side) must be unique
            for side_entry in (debit_entry, credit_entry):
                cur = conn.execute(
                    "SELECT 1 FROM trades WHERE trade_id = ? AND side = ?",
                    (side_entry.get("trade_id"), side_entry.get("side")),
                )
                if cur.fetchone():
                    continue  # already present; skip insert

                columns = TRADES_FIELDS
                placeholders = ", ".join(["?"] * len(columns))
                conn.execute(
                    f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(side_entry.get(col) for col in columns),
                )

            conn.commit()
            inserted_ids.append((debit_entry.get("trade_id"), credit_entry.get("trade_id")))

    return inserted_ids


def validate_double_entry() -> bool:
    """
    Validates that each trade_id sums to ~0 across its legs (double-entry).
    Raises if imbalance found.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT trade_id, SUM(total_value) FROM trades GROUP BY trade_id")
        imbalances = [(tid, total) for tid, total in cursor.fetchall() if tid and abs(total or 0.0) > 1e-8]
        if imbalances:
            raise RuntimeError(f"Double-entry imbalance detected for trade_ids: {imbalances}")
    return True
