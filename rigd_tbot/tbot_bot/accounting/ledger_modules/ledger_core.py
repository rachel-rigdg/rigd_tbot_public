# tbot_bot/accounting/ledger_modules/ledger_core.py

"""
Core ledger DB logic and orchestrators.
Handles generic ledger database path/identity logic and high-level coordination used by other helpers.
Implements atomic double-entry posting with strict exception propagation.
"""

import sqlite3
import uuid
from typing import Tuple, Dict, Any

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_db import _sanitize_for_sqlite  # reuse canonical sanitizer


def get_identity_tuple() -> Tuple[str, str, str, str]:
    """
    Returns (entity_code, jurisdiction_code, broker_code, bot_id) tuple from the decrypted bot identity string.
    """
    identity = load_bot_identity()
    return tuple(identity.split("_"))  # type: ignore[return-value]


def get_ledger_db_path() -> str:
    """
    Returns resolved ledger database path for the current bot identity.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)


def _insert_entries_atomic(debit_row: Dict[str, Any], credit_row: Dict[str, Any]) -> None:
    """
    Single-transaction insert of both legs. Re-raises any DB error (no swallowing).
    """
    db_path = get_ledger_db_path()
    keys = ", ".join(TRADES_FIELDS)
    placeholders = ", ".join("?" for _ in TRADES_FIELDS)

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO trades ({keys}) VALUES ({placeholders})",
                tuple(debit_row.get(k) for k in TRADES_FIELDS),
            )
            cur.execute(
                f"INSERT INTO trades ({keys}) VALUES ({placeholders})",
                tuple(credit_row.get(k) for k in TRADES_FIELDS),
            )
            conn.commit()
    except Exception as e:
        # Ensure caller sees the original failure for write-failure tests
        raise


def post_double_entry(debit: Dict[str, Any], credit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts two legs (debit/credit dicts), assigns common trade_id/group_id,
    writes both within a single atomic transaction, and returns:
      {"debit": {...}, "credit": {...}, "balanced": True/False}

    No DB exceptions are swallowed — they are re-raised.
    """
    if not isinstance(debit, dict) or not isinstance(credit, dict):
        raise TypeError("post_double_entry expects two dicts: (debit, credit)")

    # Normalize sides if not provided
    debit_leg = dict(debit)
    credit_leg = dict(credit)
    debit_leg.setdefault("side", "debit")
    credit_leg.setdefault("side", "credit")

    # Common identifiers
    common_trade_id = debit_leg.get("trade_id") or credit_leg.get("trade_id") or f"TXN-{uuid.uuid4().hex[:16]}"
    common_group_id = debit_leg.get("group_id") or credit_leg.get("group_id") or common_trade_id
    debit_leg["trade_id"] = common_trade_id
    credit_leg["trade_id"] = common_trade_id
    debit_leg["group_id"] = common_group_id
    credit_leg["group_id"] = common_group_id

    # Sanitize to schema
    debit_row = _sanitize_for_sqlite(debit_leg)
    credit_row = _sanitize_for_sqlite(credit_leg)

    # Atomic write; propagate any DB error
    _insert_entries_atomic(debit_row, credit_row)

    # Balance check (abs amounts equal)
    try:
        d_amt = float(debit_row.get("amount", 0.0))
        c_amt = float(credit_row.get("amount", 0.0))
    except Exception:
        d_amt, c_amt = 0.0, 0.0
    balanced = abs(abs(d_amt) - abs(c_amt)) < 1e-9

    return {
        "debit": debit_row,
        "credit": credit_row,
        "balanced": balanced,
    }
