# tbot_bot/accounting/ledger_modules/ledger_double_entry.py

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from typing import Dict, Iterable, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_core import (
    get_identity_tuple,
    get_conn,
    tx_context,
)
from tbot_bot.accounting.coa_mapping_table import apply_mapping_rule, load_mapping_table
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS

# Decimal policy
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN
_Q = Decimal("0.0001")


# ---- Compliance filter (backwards-compatible import) ----
try:
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import validate_entries as _validate_entries  # type: ignore

    def _is_compliant(entry: dict) -> bool:
        ok, _ = _validate_entries([entry])
        return bool(ok)
except Exception:
    try:
        from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (  # type: ignore
            is_compliant_ledger_entry as _legacy_is_compliant,
        )

        def _is_compliant(entry: dict) -> bool:
            return bool(_legacy_is_compliant(entry))
    except Exception:
        def _is_compliant(entry: dict) -> bool:  # type: ignore
            return True


def _to_dec(x) -> Decimal:
    try:
        return Decimal(str(x)).quantize(_Q)
    except Exception:
        return Decimal("0").quantize(_Q)


def _map_action(action: Optional[str]) -> str:
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


def _add_required_fields(entry: dict, ec: str, jc: str, bc: str, bid: str) -> dict:
    """
    Ensure mandatory columns exist; coerce numerics; JSON-encode complex values for SQLite.
    """
    e = dict(entry)
    # Identity
    e["entity_code"] = ec
    e["jurisdiction_code"] = jc
    e["broker_code"] = bc
    e["bot_id"] = bid

    # Defaults
    e["fee"] = 0.0 if e.get("fee") is None else e.get("fee")
    e["commission"] = 0.0 if e.get("commission") is None else e.get("commission")

    # trade_id / group_id
    if not e.get("trade_id"):
        e["trade_id"] = f"{bc}_{bid}_{hash(frozenset(e.items()))}"
    if not e.get("group_id"):
        e["group_id"] = e["trade_id"]

    # side & amounts
    side = str(e.get("side") or "").lower()
    if side not in ("debit", "credit"):
        # default to debit for safety
        side = "debit"
        e["side"] = side

    if "total_value" not in e or e["total_value"] is None:
        e["total_value"] = 0.0

    # amount derived from side
    if "amount" not in e or e["amount"] is None:
        val = _to_dec(e.get("total_value"))
        e["amount"] = float(-abs(val)) if side == "credit" else float(abs(val))

    # action / status
    e["action"] = _map_action(e.get("action"))
    if not e.get("status"):
        e["status"] = "ok"

    # Fill schema fields
    for k in TRADES_FIELDS:
        if k not in e:
            e[k] = None

    # JSON-encode complex objects
    for k, v in list(e.items()):
        if isinstance(v, (dict, list)):
            e[k] = json.dumps(v, default=str)

    # Ensure Decimal quantization applied to total_value before write
    e["total_value"] = float(_to_dec(e.get("total_value")))
    return e


def _build_splits(entries: Iterable[dict], mapping_table: Optional[dict], group_id_hint: Optional[str]) -> List[dict]:
    """
    Accepts raw entries (without side) or prepared splits (with side).
    Ensures each logical input results in exactly two legs (debit/credit) with the same group_id.
    """
    # Determine if entries are already split
    entries = list(entries)
    has_side = any(isinstance(e, dict) and e.get("side") for e in entries)

    if has_side:
        # Assume caller provided debit/credit splits; ensure group_id propagation
        splits: List[dict] = []
        for e in entries:
            ee = dict(e)
            if group_id_hint and not ee.get("group_id"):
                ee["group_id"] = group_id_hint
            splits.append(ee)
        return splits

    # Raw entries → use mapping to create debit/credit legs
    ec, jc, bc, bid = get_identity_tuple()
    if mapping_table is None:
        mapping_table = load_mapping_table(ec, jc, bc, bid)

    splits = []
    for e in entries:
        debit, credit = apply_mapping_rule(e, mapping_table)
        # Preserve/propagate group_id
        gid = e.get("group_id") or e.get("trade_id") or group_id_hint
        if gid:
            debit.setdefault("group_id", gid)
            credit.setdefault("group_id", gid)
        splits.extend([debit, credit])
    return splits


def _enforce_group_balance(splits: List[dict]) -> None:
    """
    Enforce that the sum of splits per group_id (or trade_id fallback) equals zero (Decimal, quantized).
    """
    groups = defaultdict(list)
    for s in splits:
        key = s.get("group_id") or s.get("trade_id") or "__ungrouped__"
        groups[key].append(_to_dec(s.get("total_value")))

    for key, vals in groups.items():
        total = sum(vals, Decimal("0")).quantize(_Q)
        if total != Decimal("0").quantize(_Q):
            raise ValueError(f"Double-entry imbalance for group '{key}': {total}")


def post_ledger_entries_double_entry(entries: Iterable[dict], group_id: Optional[str] = None) -> List[int]:
    """
    Public entrypoint.
    - Accepts raw entries or prepared splits.
    - Builds splits, enforces group sum==0 (Decimal), and inserts both sides atomically.
    - Returns DB row IDs inserted (list[int]).
    """
    ec, jc, bc, bid = get_identity_tuple()

    # Build and normalize splits
    splits = _build_splits(entries, mapping_table=None, group_id_hint=group_id)

    # Compliance filter (non-mutating)
    filtered = [s for s in splits if _is_compliant(s)]
    if not filtered:
        return []

    # Enforce group balance (Decimal)
    _enforce_group_balance(filtered)

    inserted_ids: List[int] = []
    with tx_context() as conn:
        for s in filtered:
            # Append identity defaults, amounts, etc., and quantize Decimal
            s_norm = _add_required_fields(s, ec, jc, bc, bid)

            # Dedup check: (trade_id, side) pair (best-effort)
            dup = conn.execute(
                "SELECT id FROM trades WHERE trade_id = ? AND side = ? LIMIT 1",
                (s_norm.get("trade_id"), s_norm.get("side")),
            ).fetchone()
            if dup:
                continue

            cols = TRADES_FIELDS
            placeholders = ", ".join(["?"] * len(cols))
            cur = conn.execute(
                f"INSERT INTO trades ({', '.join(cols)}) VALUES ({placeholders})",
                tuple(s_norm.get(c) for c in cols),
            )
            inserted_ids.append(int(cur.lastrowid))

    return inserted_ids


# Backward-compatible alias expected by older callers
def post_double_entry(entries: Iterable[dict], mapping_table: Optional[dict] = None) -> List[int]:
    return post_ledger_entries_double_entry(entries)


def validate_double_entry() -> bool:
    """
    Validates that each trade_id sums to zero across its legs (Decimal-aware).
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT trade_id, SUM(total_value) FROM trades GROUP BY trade_id").fetchall()
        imbalances = [
            (r[0], float(Decimal(str(r[1] or 0)).quantize(_Q)))
            for r in rows
            if Decimal(str(r[1] or 0)).quantize(_Q) != Decimal("0").quantize(_Q)
        ]
        if imbalances:
            raise RuntimeError(f"Double-entry imbalance detected for trade_ids: {imbalances}")
    return True
