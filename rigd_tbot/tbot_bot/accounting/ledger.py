# tbot_bot/accounting/ledger.py
# Central ledger façade: single entrypoints for posting/querying.
# Orchestrates: compliance → mapping → double-entry within an atomic transaction.
# Enforces tz-aware UTC timestamps and Decimal-only math.

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, getcontext, ROUND_HALF_EVEN
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Public utilities still re-exported for compatibility
from tbot_bot.accounting.ledger_modules.ledger_account_map import (  # noqa: F401
    load_broker_code,
    load_account_number,
    get_account_path,
)
from tbot_bot.accounting.ledger_modules.ledger_entry import (  # noqa: F401
    get_identity_tuple,
    load_internal_ledger,
    add_ledger_entry,
    mark_entry_resolved,
)
from tbot_bot.accounting.ledger_modules.ledger_edit import (  # noqa: F401
    edit_ledger_entry,
    delete_ledger_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_double_entry import post_ledger_entries_double_entry  # noqa: F401
from tbot_bot.accounting.ledger_modules.ledger_hooks import (  # noqa: F401
    post_tax_reserve_entry,
    post_payroll_reserve_entry,
    post_float_allocation_entry,
    post_rebalance_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger  # noqa: F401
from tbot_bot.accounting.ledger_modules.ledger_grouping import (  # noqa: F401
    fetch_grouped_trades,
    fetch_trade_group_by_id,
    collapse_expand_group,
)

# Mapping + Compliance (module-level imports with graceful fallbacks)
from tbot_bot.accounting.coa_mapping_table import apply_mapping_rule  # versioned COA mapping

try:
    # prefer dedicated TX context if available
    from tbot_bot.accounting.ledger_modules.ledger_core import tx_context as _tx_context  # type: ignore
except Exception:
    @contextmanager
    def _tx_context():
        yield

try:
    # compliance module may expose different entrypoints; normalize to _run_compliance(...)
    from tbot_bot.accounting.ledger_modules import ledger_compliance_filter as _compliance  # type: ignore
except Exception:  # pragma: no cover
    _compliance = None  # type: ignore

try:
    from tbot_bot.accounting.ledger_modules import ledger_query as _lq  # type: ignore
except Exception:  # pragma: no cover
    _lq = None  # type: ignore


# -----------------------
# Local helpers
# -----------------------

getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN

_DEC_Q = Decimal("0.0001")  # default quantization for cash amounts unless specified by currency


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(val) -> Decimal:
    if isinstance(val, Decimal):
        d = val
    elif isinstance(val, (int, float, str)):
        d = Decimal(str(val))
    else:
        raise TypeError(f"Unsupported amount type: {type(val)}")
    return d.quantize(_DEC_Q)


def _normalize_entry(e: Dict) -> Dict:
    out = dict(e)
    # Ensure tz-aware UTC timestamp
    if not out.get("timestamp_utc"):
        out["timestamp_utc"] = _utc_now_iso()
    # Normalize numeric fields to Decimal strings for later DB layer
    if "total_value" in out:
        out["total_value"] = _to_decimal(out["total_value"])
    return out


def _run_compliance(batch: Sequence[Dict]) -> Tuple[bool, List[str]]:
    if _compliance is None:
        return True, []
    # Duck-typing: support common names
    for fname in ("validate_batch", "validate_entries", "validate"):
        fn = getattr(_compliance, fname, None)
        if callable(fn):
            res = fn(batch)  # expected (ok: bool, errors: list[str]) or raises
            if isinstance(res, tuple) and len(res) == 2:
                return bool(res[0]), list(res[1])
            return True, []
    return True, []


# -----------------------
# Public façade API
# -----------------------

def post_entries(group: Iterable[Dict]) -> Tuple[str, List[int]]:
    """
    Accepts an iterable of raw accounting 'entry' dicts (broker/strategy/total_value/etc).
    Pipeline:
      1) Normalize (UTC, Decimal)
      2) Map → debit/credit splits via COA mapping (apply_mapping_rule)
      3) Compliance validate
      4) Atomic double-entry post; rollback on any failure
    Returns: (group_id, inserted_ids)
    """
    group_id = str(uuid.uuid4())
    normalized: List[Dict] = [_normalize_entry(e) for e in group]

    # Build splits
    splits: List[Dict] = []
    for e in normalized:
        debit, credit = apply_mapping_rule(e)
        # Decimal-only math
        debit["total_value"] = _to_decimal(debit.get("total_value", 0))
        credit["total_value"] = _to_decimal(credit.get("total_value", 0))
        # Propagate group id & timestamp
        debit.setdefault("group_id", group_id)
        credit.setdefault("group_id", group_id)
        debit.setdefault("timestamp_utc", e.get("timestamp_utc") or _utc_now_iso())
        credit.setdefault("timestamp_utc", e.get("timestamp_utc") or _utc_now_iso())
        splits.extend([debit, credit])

    # Compliance
    ok, errors = _run_compliance(splits)
    if not ok:
        raise ValueError(f"Ledger compliance failed: {errors}")

    # Atomic posting
    with _tx_context():
        result = None
        try:
            # New API shape typically returns a dict with inserted_ids
            result = post_ledger_entries_double_entry(splits, group_id=group_id)  # type: ignore[arg-type]
        except TypeError:
            result = post_ledger_entries_double_entry(splits)  # type: ignore[call-arg]

        # Normalize result to a list of ints
        if isinstance(result, dict) and "inserted_ids" in result:
            inserted_ids = list(map(int, result.get("inserted_ids") or []))
        elif isinstance(result, (list, tuple)):
            inserted_ids = list(map(int, result))
        else:
            inserted_ids = [int(result)] if result is not None else []

    return group_id, inserted_ids


def post_trade(fill: Dict) -> Tuple[str, List[int]]:
    """
    Convenience wrapper for a single trade fill dict.
    """
    return post_entries([fill])


def post_cash(txn: Dict) -> Tuple[str, List[int]]:
    """
    Convenience wrapper for a single cash transaction dict.
    """
    return post_entries([txn])


# -----------------------
# Read/query façade
# -----------------------

def query_entries(**filters):
    """
    Proxy to ledger_query.query_entries(**filters)
    """
    if _lq is None or not hasattr(_lq, "query_entries"):
        raise RuntimeError("ledger_query.query_entries is unavailable")
    return _lq.query_entries(**filters)


def query_splits(**filters):
    """
    Proxy to ledger_query.query_splits(**filters)
    """
    if _lq is None or not hasattr(_lq, "query_splits"):
        raise RuntimeError("ledger_query.query_splits is unavailable")
    return _lq.query_splits(**filters)


def query_balances(**filters):
    """
    Proxy to ledger_query.query_balances(**filters)
    """
    if _lq is None or not hasattr(_lq, "query_balances"):
        raise RuntimeError("ledger_query.query_balances is unavailable")
    return _lq.query_balances(**filters)


__all__ = [
    # façade
    "post_entries",
    "post_trade",
    "post_cash",
    "query_entries",
    "query_splits",
    "query_balances",
    # legacy exports
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
