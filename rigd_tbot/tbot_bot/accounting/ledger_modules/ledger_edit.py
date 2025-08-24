# tbot_bot/accounting/ledger_modules/ledger_edit.py

"""
Ledger edit helpers (v048)
- No UPDATE/DELETE to primary tables.
- Edits are modeled as: (1) reversing entries for the original group, then (2) posting corrected entries.
- Deletions are modeled as: reversing entries for the original group (optional soft-delete flags if schema supports).
- Every action is audited with audit_reference.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_core import get_conn, tx_context
from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
    post_ledger_entries_double_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_audit import log_audit_event
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS


# -----------------
# Internal helpers
# -----------------

def _row_to_dict(row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}

def _fetch_entry_and_group(entry_id: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Load the target row and all rows in its group_id (atomic read).
    """
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM trades WHERE id = ?", (entry_id,)).fetchone()
        if not r:
            raise ValueError(f"Entry id {entry_id} not found")
        entry = _row_to_dict(r)
        gid = entry.get("group_id") or entry.get("trade_id")
        rows = conn.execute(
            "SELECT * FROM trades WHERE (group_id = ? OR (group_id IS NULL AND trade_id = ?)) ORDER BY id",
            (gid, entry.get("trade_id")),
        ).fetchall()
        group = [_row_to_dict(x) for x in rows] if rows else [entry]
        return entry, group

def _swap_side(side: str) -> str:
    return "debit" if str(side).lower() == "credit" else "credit"

def _build_reversal_splits(group_rows: List[Dict[str, Any]], reason: str, audit_reference: str) -> List[Dict[str, Any]]:
    """
    For each split in the original group, build a single reversing split:
    - same account, symbol, etc.
    - side swapped (debit<->credit)
    - total_value sign inverted
    """
    rev: List[Dict[str, Any]] = []
    for r in group_rows:
        e = {
            # identity/context will be filled by posting helper
            "group_id": r.get("group_id") or r.get("trade_id"),
            "trade_id": f"{r.get('trade_id')}-REV",
            "symbol": r.get("symbol"),
            "account": r.get("account"),
            "action": "correction_reversal",
            "side": _swap_side(r.get("side")),
            "total_value": -(r.get("total_value") or 0.0),
            "price": r.get("price"),
            "quantity": r.get("quantity"),
            "commission": r.get("commission"),
            "fee": r.get("fee"),
            "currency": r.get("currency"),
            "status": "ok",
            "fitid": None,  # new row; avoid conflicting unique fitid
            "audit_reference": audit_reference,
            "json_metadata": {"reversal_of_id": r.get("id"), "reason": reason},
        }
        # Ensure all schema keys exist to satisfy inserts (non-mutating of originals)
        for k in TRADES_FIELDS:
            e.setdefault(k, None)
        rev.append(e)
    return rev

def _schema_soft_delete_columns(conn) -> List[str]:
    cols = [row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()]
    candidates = []
    for c in ("deleted", "is_deleted", "deleted_at_utc", "deleted_by"):
        if c in cols:
            candidates.append(c)
    return candidates


# -----------------
# Public API
# -----------------

def edit_ledger_entry(entry_id: int, updated_data: Dict[str, Any], *, user: str = "system", reason: str = "edit_correction") -> List[int]:
    """
    Perform an edit by reversal+correction:
      1) Reverse all splits in the original group.
      2) Post corrected entry (raw); double-entry module will create balanced splits.
    Returns list of inserted row IDs (reversal + correction legs).
    """
    # Load original + group
    original, group = _fetch_entry_and_group(entry_id)
    audit_ref = f"edit:{entry_id}"

    # 1) Post reversing splits (as prepared splits with sides)
    reversal_splits = _build_reversal_splits(group, reason, audit_ref)
    rev_ids = post_ledger_entries_double_entry(reversal_splits)

    # 2) Post corrected entry (raw). Do NOT mutate caller payload.
    corrected = dict(updated_data)
    corrected.setdefault("action", original.get("action"))
    corrected.setdefault("symbol", original.get("symbol"))
    corrected.setdefault("currency", original.get("currency"))
    corrected.setdefault("commission", original.get("commission"))
    corrected.setdefault("fee", original.get("fee"))
    corrected.setdefault("broker", original.get("broker_code"))
    corrected.setdefault("code", original.get("code"))
    # Link correction logically to original group
    corrected.setdefault("json_metadata", {})
    if isinstance(corrected["json_metadata"], dict):
        corrected["json_metadata"].setdefault("correction_of_group", original.get("group_id") or original.get("trade_id"))
        corrected["json_metadata"].setdefault("reason", reason)
    corrected.setdefault("audit_reference", audit_ref)

    corr_ids = post_ledger_entries_double_entry([corrected])

    # Audit the operation (before=original group; after=caller payload)
    try:
        log_audit_event(
            action="edit_correction",
            entry_id=entry_id,
            user=user,
            before={"group": group},
            after={"updated_data": updated_data},
            reason=reason,
            audit_reference=audit_ref,
            group_id=original.get("group_id"),
            fitid=original.get("fitid"),
            extra={"inserted_ids": rev_ids + corr_ids},
        )
    except Exception:
        # Audit should never break the flow
        pass

    return list(rev_ids) + list(corr_ids)


def delete_ledger_entry(entry_id: int, *, user: str = "system", reason: str = "delete_reversal") -> List[int]:
    """
    Perform a deletion by reversal only (no hard DELETE):
      - Reverse all splits in the original group.
      - Optionally set soft-delete flags if supported by schema.
    Returns list of inserted reversal row IDs.
    """
    original, group = _fetch_entry_and_group(entry_id)
    audit_ref = f"delete:{entry_id}"

    # Post reversing splits
    reversal_splits = _build_reversal_splits(group, reason, audit_ref)
    rev_ids = post_ledger_entries_double_entry(reversal_splits)

    # Optional soft-delete flags on originals (schema-permitting)
    try:
        with tx_context() as conn:
            cols = _schema_soft_delete_columns(conn)
            if cols:
                sets = []
                params: List[Any] = []
                if "deleted" in cols:
                    sets.append("deleted = 1")
                if "is_deleted" in cols:
                    sets.append("is_deleted = 1")
                if "deleted_by" in cols:
                    sets.append("deleted_by = ?")
                    params.append(user)
                if "deleted_at_utc" in cols:
                    sets.append("deleted_at_utc = CURRENT_TIMESTAMP")
                sql = f"UPDATE trades SET {', '.join(sets)} WHERE id IN ({', '.join(['?'] * len(group))})"
                params.extend([g["id"] for g in group])
                conn.execute(sql, tuple(params))
    except Exception:
        # Soft-delete is best-effort; never block reversals
        pass

    # Audit
    try:
        log_audit_event(
            action="delete_reversal",
            entry_id=entry_id,
            user=user,
            before={"group": group},
            after=None,
            reason=reason,
            audit_reference=audit_ref,
            group_id=original.get("group_id"),
            fitid=original.get("fitid"),
            extra={"inserted_ids": rev_ids},
        )
    except Exception:
        pass

    return list(rev_ids)
