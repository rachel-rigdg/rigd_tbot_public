# tbot_bot/accounting/ledger_modules/ledger_compliance_filter.py

"""
Ledger compliance filter for validating transactions before they are written to the ledger.
Used by sync, holdings, and any module that creates/imports ledger entries.

Key rules:
- Reject completely blank primary-field entries.
- Reject unmapped/unsupported actions.
- Reject non-economic $0.00 "noise" events (partials, status markers) with no fees.
- Allow legitimate economic events (including fees-only edge cases in the future).
"""

from typing import Any, Dict, List, Optional, Tuple
from tbot_bot.accounting.ledger_modules.ledger_fields import ALLOWED_TRADE_ACTIONS as _CANON_ACTIONS

# Primary UI/display fields — used to detect completely blank records
PRIMARY_FIELDS = ("symbol", "datetime_utc", "action", "price", "quantity", "total_value")

# Keep ops/system hooks allowed in addition to canonical trade actions
_OPS_ACTIONS = {
    "reserve_tax", "reserve_payroll", "float_allocation", "rebalance_buy", "rebalance_sell",
}
_ALLOWED_ACTIONS = set(_CANON_ACTIONS) | _OPS_ACTIONS


def _is_blank_primary(entry: Dict[str, Any]) -> bool:
    """True if all primary display fields are None/empty strings."""
    return all(entry.get(f) is None or str(entry.get(f)).strip() == "" for f in PRIMARY_FIELDS)


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        # guard against "", None, "None"
        if x is None or (isinstance(x, str) and x.strip() in ("", "None")):
            return default
        return float(x)
    except Exception:
        return default


def _is_zero_value_spurious(entry: Dict[str, Any]) -> bool:
    """
    Filter out non-economic broker events that normalize into $0.00 entries, e.g.
    new/accepted/canceled/partial markers with zero qty/price/val and no fees.
    This function must be completely safe if metadata/raw payloads are missing.
    """
    qty = _as_float(entry.get("quantity"))
    price = _as_float(entry.get("price"))
    # Prefer provided total_value; otherwise compute qty * price
    total_value = _as_float(entry.get("total_value"), qty * price)
    fees = _as_float(entry.get("fee")) + _as_float(entry.get("commission"))

    # SAFELY unwrap metadata/raw hints (no AttributeError on None)
    jm = entry.get("json_metadata") or {}
    raw = {}
    if isinstance(jm, dict):
        raw = jm.get("raw_broker") or jm.get("raw") or {}
        if not isinstance(raw, dict):
            raw = {}

    # Pull a raw broker state hint if present
    raw_type = str(
        (raw.get("activity_type") or raw.get("type") or raw.get("order_status") or "")
    ).upper()

    non_economic_markers = {
        "NEW", "PENDING_NEW", "ACCEPTED", "CANCELED", "CANCELLED", "REPLACED", "REJECTED", "EXPIRED",
        "PARTIAL_FILL", "PARTIALLY_FILLED", "PENDING_CANCEL",
        # We will only drop "FILL" if economics are actually zero
        "FILL",
    }

    # If there’s literally no economic effect and no fees, drop it when it looks like a status/partial record
    if (qty == 0 or price == 0 or total_value == 0) and fees == 0 and raw_type in non_economic_markers:
        return True
    return False


def compliance_filter_entry(entry: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate a single entry. Returns (allowed, reason_if_rejected).
    Conservative: ambiguous items are rejected for upstream review.
    """
    if not isinstance(entry, dict):
        return False, "not_a_dict"

    # Primary blank check
    if _is_blank_primary(entry):
        return False, "blank_primary_fields"

    # Action check (must already be mapped to ledger actions)
    action = entry.get("action")
    if action not in _ALLOWED_ACTIONS:
        return False, "unmapped_action"

    # Economic noise filter for $0 entries (e.g., partials/cancels)
    if _is_zero_value_spurious(entry):
        return False, "zero_value_spurious"

    # Basic ID sanity
    if not entry.get("trade_id"):
        return False, "missing_trade_id"

    return True, None


def compliance_filter_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Batch version: returns only entries that pass compliance."""
    passed: List[Dict[str, Any]] = []
    for e in entries:
        ok, _ = compliance_filter_entry(e)
        if ok:
            passed.append(e)
    return passed
