# tbot_bot/accounting/ledger_modules/ledger_double_entry.py

from __future__ import annotations

import uuid
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


def _ensure_timestamp_utc(e: dict) -> None:
    # prefer provided timestamp_utc, else fall back to datetime_utc, else now-UTC
    from datetime import datetime, timezone
    ts = e.get("timestamp_utc") or e.get("datetime_utc")
    if not ts:
        ts = datetime.now(timezone.utc).isoformat()
    e["timestamp_utc"] = ts


def _quantize_money_fields(e: dict) -> None:
    """Quantize all money-like fields to _Q in-place."""
    for k in ("total_value", "amount", "commission", "fee", "accrued_interest", "tax", "net_amount"):
        if k in e and e[k] is not None:
            e[k] = float(_to_dec(e[k]))


def _normalize_total_value_sign(e: dict) -> None:
    """Ensure total_value sign aligns with side (debit=+, credit=-)."""
    side = str(e.get("side") or "").lower()
    val = _to_dec(e.get("total_value"))
    if side == "credit":
        val = -abs(val)
    else:  # default debit
        val = abs(val)
    e["total_value"] = float(val)


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
        side = "debit"
        e["side"] = side

    if "total_value" not in e or e["total_value"] is None:
        e["total_value"] = 0.0

    # amount derived from side when absent
    if "amount" not in e or e["amount"] is None:
        val = _to_dec(e.get("total_value"))
        e["amount"] = float(-abs(val)) if side == "credit" else float(abs(val))

    # action / status
    e["action"] = _map_action(e.get("action"))
    if not e.get("status"):
        e["status"] = "ok"

    # Ensure timestamps
    _ensure_timestamp_utc(e)

    # Quantize money and enforce total_value sign by side
    _quantize_money_fields(e)
    _normalize_total_value_sign(e)

    # Fill schema fields
    for k in TRADES_FIELDS:
        if k not in e:
            e[k] = None

    # JSON-encode complex objects
    for k, v in list(e.items()):
        if isinstance(v, (dict, list)):
            e[k] = json.dumps(v, default=str)

    return e


def _build_splits(entries: Iterable[dict], mapping_table: Optional[dict], group_id_hint: Optional[str]) -> Tuple[List[dict], str]:
    """
    Accepts raw entries (without side) or prepared splits (with side).
    Ensures each logical input results in exactly two legs (debit/credit) with the same group_id.
    Returns (splits, group_id_out) where group_id_out is the first group's id (useful for tests/UX).
    """
    # Determine if entries are already split
    items = list(entries)
    has_side = any(isinstance(e, dict) and e.get("side") for e in items)

    # Choose/propagate batch group_id if provided or generate one when all missing
    group_out = (group_id_hint or "").strip()
    if not group_out:
        # If any entry has a group_id use it; otherwise generate a new UUID (kept internal; legs still get per-entry group)
        for e in items:
            if isinstance(e, dict) and e.get("group_id"):
                group_out = str(e.get("group_id"))
                break
        if not group_out:
            group_out = str(uuid.uuid4())

    if has_side:
        # Assume caller provided debit/credit splits; ensure group_id propagation if missing
        splits: List[dict] = []
        for e in items:
            ee = dict(e)
            ee.setdefault("group_id", group_id_hint or ee.get("trade_id") or group_out)
            splits.append(ee)
        return splits, splits[0].get("group_id") if splits else group_out

    # Raw entries → use mapping to create debit/credit legs
    ec, jc, bc, bid = get_identity_tuple()
    if mapping_table is None:
        mapping_table = load_mapping_table(ec, jc, bc, bid)

    splits = []
    for e in items:
        debit, credit = apply_mapping_rule(e, mapping_table)
        # Preserve/propagate group_id
        gid = e.get("group_id") or e.get("trade_id") or group_id_hint or group_out
        debit.setdefault("group_id", gid)
        credit.setdefault("group_id", gid)
        splits.extend([debit, credit])
    return splits, splits[0].get("group_id") if splits else group_out


def _enforce_group_balance(splits: List[dict]) -> List[Tuple[str, Decimal]]:
    """
    Enforce that the sum of splits per group_id (or trade_id fallback) equals zero (Decimal, quantized).
    Returns a list of (group_key, total) for any imbalanced groups (empty if all balanced).
    """
    groups = defaultdict(list)
    for s in splits:
        key = s.get("group_id") or s.get("trade_id") or "__ungrouped__"
        groups[key].append(_to_dec(s.get("total_value")))

    imbalances: List[Tuple[str, Decimal]] = []
    for key, vals in groups.items():
        total = sum(vals, Decimal("0")).quantize(_Q)
        if total != Decimal("0").quantize(_Q):
            imbalances.append((key, total))
    if imbalances:
        return imbalances
    return []


def post_ledger_entries_double_entry(entries: Iterable[dict], group_id: Optional[str] = None) -> Dict[str, object]:
    """
    Public entrypoint. ATOMIC per batch.
    - Accepts raw entries or prepared splits.
    - Builds splits, enforces group/batch sum==0 (Decimal), and inserts both sides atomically.
    - Quantizes money fields before insert.
    - Returns dict:
        {
          "inserted_ids": [int, ...],
          "group_id": "<first-group-id>",
          "balanced": True|False,
          "imbalances": [(group_key, total_decimal_as_str), ...]
        }
    """
    ec, jc, bc, bid = get_identity_tuple()

    # Build and normalize splits
    splits, group_out = _build_splits(entries, mapping_table=None, group_id_hint=group_id)

    # Compliance filter (non-mutating)
    filtered = [s for s in splits if _is_compliant(s)]
    if not filtered:
        return {"inserted_ids": [], "group_id": group_out, "balanced": True, "imbalances": []}

    # Prepare normalized rows (quantized money, timestamps, sign enforcement)
    normalized = []
    for s in filtered:
        n = _add_required_fields(s, ec, jc, bc, bid)
        normalized.append(n)

    # ATOMIC block: verify balance and then insert
    inserted_ids: List[int] = []
    with tx_context() as conn:
        # (1) Per-group balance check
        imbalances = _enforce_group_balance(normalized)
        # (2) Batch-wide balance check
        batch_total = sum((_to_dec(x.get("total_value")) for x in normalized), Decimal("0")).quantize(_Q)
        if batch_total != Decimal("0").quantize(_Q):
            imbalances.append(("*batch*", batch_total))

        if imbalances:
            # Abort the transaction by raising (auto-rollback by tx_context)
            raise ValueError(f"Double-entry imbalance: {[(k, str(v)) for k, v in imbalances]}")

        # Insert rows
        for s_norm in normalized:
            # Best-effort dedup check on (trade_id, side)
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

    return {
        "inserted_ids": inserted_ids,
        "group_id": group_out,
        "balanced": True,
        "imbalances": [],
    }


# Backward-compatible alias expected by older callers
def post_double_entry(entries: Iterable[dict], mapping_table: Optional[dict] = None):
    """
    Legacy wrapper: returns only the list of inserted IDs to keep older callers working.
    New code should use post_ledger_entries_double_entry().
    """
    res = post_ledger_entries_double_entry(entries)
    return res.get("inserted_ids", [])


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
