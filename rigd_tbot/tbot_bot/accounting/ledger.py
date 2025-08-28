# tbot_bot/accounting/ledger.py

# Central ledger orchestration module.
# Delegates all logic to accounting/ledger/ helpers.
# No business logic; just high-level API and imports.

from typing import Any, Dict, List, Tuple, Union

from tbot_bot.accounting.ledger_modules.ledger_account_map import (
    load_broker_code,
    load_account_number,
    get_account_path,
)
from tbot_bot.accounting.ledger_modules.ledger_entry import (
    get_identity_tuple,
    load_internal_ledger,
    add_ledger_entry,
    edit_ledger_entry,
    delete_ledger_entry,
    mark_entry_resolved,
)
# Import the implementation under an alias so we can provide a wrapper with corrected semantics
from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
    post_ledger_entries_double_entry as _impl_post_ledger_entries_double_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_hooks import (
    post_tax_reserve_entry,
    post_payroll_reserve_entry,
    post_float_allocation_entry,
    post_rebalance_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_sync import (
    sync_broker_ledger,
)
from tbot_bot.accounting.ledger_modules.ledger_grouping import (
    fetch_grouped_trades,
    fetch_trade_group_by_id,
    collapse_expand_group,
)


def _normalize_double_entry_result(
    result: Any
) -> Dict[str, Any]:
    """
    Normalize various legacy return shapes from the underlying implementation
    into a stable dict payload for UI/tests.

    Target shape:
      {
        "balanced": bool | None,
        "posted": int,
        "debits": float | None,
        "credits": float | None,
        # optionally: "raw": <original result>  (only when unknown)
      }
    """
    # If the implementation already returns a dict with desired keys, pass it through.
    if isinstance(result, dict) and (
        "balanced" in result or "posted" in result or "debits" in result or "credits" in result
    ):
        # Make sure all keys exist
        return {
            "balanced": result.get("balanced"),
            "posted": result.get("posted", 0),
            "debits": result.get("debits"),
            "credits": result.get("credits"),
            **{k: v for k, v in result.items() if k not in {"balanced", "posted", "debits", "credits"}},
        }

    # Tuple/list of four values: (balanced, posted, debits, credits)
    if isinstance(result, (list, tuple)) and len(result) == 4 and isinstance(result[0], (bool, int)):
        return {
            "balanced": bool(result[0]),
            "posted": int(result[1]),
            "debits": float(result[2]),
            "credits": float(result[3]),
        }

    # List of leg dicts; compute totals
    if isinstance(result, list) and result and isinstance(result[0], dict):
        legs: List[Dict[str, Any]] = result
        posted = len(legs)
        debits = 0.0
        credits = 0.0
        for leg in legs:
            amt = leg.get("amount", 0.0)
            try:
                amt = float(amt)
            except Exception:
                amt = 0.0
            dc = (leg.get("debit_credit") or leg.get("dc") or "").strip().lower()
            if dc in ("d", "debit"):
                debits += abs(amt)
            elif dc in ("c", "credit"):
                credits += abs(amt)
            else:
                # Fallback heuristic: non-negative -> debit, negative -> credit
                if amt >= 0:
                    debits += amt
                else:
                    credits += -amt
        balanced = round(debits - credits, 8) == 0.0
        return {"balanced": balanced, "posted": posted, "debits": debits, "credits": credits}

    # Unknown shape: provide minimal info and include raw for debugging
    try:
        posted = len(result)  # may raise
    except Exception:
        posted = 0
    return {"balanced": None, "posted": posted, "debits": None, "credits": None, "raw": result}


def post_ledger_entries_double_entry(*args, **kwargs) -> Dict[str, Any]:
    """
    Wrapper to enforce:
      - dict payload result for UI/tests
      - no swallowing of DB write errors (re-raise)
    """
    # Let any exception from the implementation bubble up (tests/UI need to detect failures).
    result = _impl_post_ledger_entries_double_entry(*args, **kwargs)

    # If the implementation signaled failure via a dict, convert to an exception so callers see it.
    if isinstance(result, dict) and result.get("ok") is False:
        # Preserve useful error info if present.
        msg = result.get("error") or "double-entry post failed"
        raise RuntimeError(msg)

    return _normalize_double_entry_result(result)


__all__ = [
    "load_broker_code",
    "load_account_number",
    "get_account_path",
    "get_identity_tuple",
    "load_internal_ledger",
    "add_ledger_entry",
    "edit_ledger_entry",
    "delete_ledger_entry",
    "mark_entry_resolved",
    "post_ledger_entries_double_entry",
    "post_tax_reserve_entry",
    "post_payroll_reserve_entry",
    "post_float_allocation_entry",
    "post_rebalance_entry",
    "sync_broker_ledger",
    "fetch_grouped_trades",
    "fetch_trade_group_by_id",
    "collapse_expand_group",
]
