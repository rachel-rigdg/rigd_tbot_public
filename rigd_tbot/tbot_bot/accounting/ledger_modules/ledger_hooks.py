# tbot_bot/accounting/ledger_modules/ledger_hooks.py

"""
Post-commit ledger hooks (v048)

- Posting helpers for system/reserve actions (tax, payroll, float, rebalance).
- After DB commit: recalc balances, enqueue snapshots, emit local notifications.
- Never perform network I/O inside a DB transaction (hooks run after posting returns).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_account_map import get_account_path, load_broker_code
from tbot_bot.accounting.ledger_modules.ledger_double_entry import post_ledger_entries_double_entry
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_balance import calculate_account_balances
from tbot_bot.accounting.ledger_modules.ledger_grouping import propagate_group_id
from tbot_bot.accounting.ledger_modules.ledger_core import get_ledger_db_path

# Optional snapshot module
try:
    from tbot_bot.accounting.ledger_modules import ledger_snapshot as _snapshot  # type: ignore
except Exception:  # pragma: no cover
    _snapshot = None  # type: ignore

# Decimal policy
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN
_Q = Decimal("0.0001")


# -----------------
# Utilities
# -----------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dec(x) -> Decimal:
    try:
        return Decimal(str(x)).quantize(_Q)
    except Exception:
        return Decimal("0").quantize(_Q)


def _current_user() -> str:
    try:
        from tbot_web.support.auth_web import get_current_user  # type: ignore
        u = get_current_user()
        return getattr(u, "username", None) or (u if isinstance(u, str) else "system")
    except Exception:
        return "system"


def _paths():
    base = Path(get_ledger_db_path()).parent
    outbox = base / "outbox"
    cache = base / "cache"
    queues = base / "queues"
    outbox.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    queues.mkdir(parents=True, exist_ok=True)
    return outbox, cache, queues


def _jsonl_append(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _notify_local(event: Dict[str, Any]) -> None:
    outbox, _, _ = _paths()
    _jsonl_append(outbox / "notifications_outbox.jsonl", {"ts_utc": _utc_now_iso(), **event})


def _enqueue_snapshot_local(as_of_iso: str) -> None:
    _, _, queues = _paths()
    _jsonl_append(queues / "snapshot_queue.jsonl", {"ts_utc": _utc_now_iso(), "as_of_utc": as_of_iso})


def _write_balances_cache(snapshot: Dict[str, Any]) -> None:
    _, cache, _ = _paths()
    with (cache / "balances_last.json").open("w", encoding="utf-8") as f:
        json.dump({"ts_utc": _utc_now_iso(), "balances": snapshot}, f, indent=2)


def _run_post_commit_hooks(group_id: str, inserted_ids: List[int], as_of_utc: Optional[str] = None) -> None:
    """
    Execute post-commit hooks:
      - Recalculate balances as-of (cached locally)
      - Enqueue snapshots (module or local queue)
      - Notify local outbox
    """
    # 1) Recalc balances (no DB writes beyond normal reads)
    balances = calculate_account_balances(as_of_utc)
    _write_balances_cache(balances)

    # 2) Snapshot enqueue
    as_of = as_of_utc or _utc_now_iso()
    if _snapshot and hasattr(_snapshot, "enqueue_snapshot"):
        try:
            _snapshot.enqueue_snapshot(as_of)  # type: ignore[attr-defined]
        except Exception:
            _enqueue_snapshot_local(as_of)
    else:
        _enqueue_snapshot_local(as_of)

    # 3) Local notification (no network I/O)
    _notify_local(
        {
            "type": "ledger_post_commit",
            "group_id": group_id,
            "inserted_count": len(inserted_ids),
            "inserted_ids": inserted_ids,
        }
    )


# -----------------
# Entry builders
# -----------------

def _build_entry(*, action: str, side: str, amount, timestamp_utc: Optional[str], account_code: str,
                 strategy: str, tags: List[str], notes: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    Minimal normalized entry (double-entry module fills identity & other defaults).
    """
    amt = _to_dec(amount)
    if side.lower() == "credit" and amt > 0:
        amt = -amt
    if side.lower() == "debit" and amt < 0:
        amt = -amt

    entry: Dict[str, Any] = {
        "timestamp_utc": timestamp_utc or _utc_now_iso(),
        "action": action,
        "side": side.lower(),
        "symbol": symbol,
        "quantity": None,
        "price": None,
        "total_value": float(amt),
        "amount": float(amt),
        "commission": 0.0,
        "fee": 0.0,
        "currency": "USD",
        "account": get_account_path(account_code, side="debit" if amt >= 0 else "credit"),
        "trade_id": None,
        "group_id": None,  # filled by propagate_group_id
        "fitid": None,
        "strategy": strategy,
        "tags": json.dumps(tags or [], ensure_ascii=False),
        "description": notes or "",
        "status": "ok",
        "approval_status": "pending",
        "created_by": _current_user(),
        "updated_by": None,
        "response_hash": None,
        "sync_run_id": None,
        "json_metadata": json.dumps({"hook": action}, ensure_ascii=False),
        "created_at_utc": None,
        "updated_at_utc": None,
    }
    # Ensure all schema keys exist (order alignment elsewhere)
    for k in TRADES_FIELDS:
        entry.setdefault(k, None)
    return entry


# -----------------
# Public posting helpers (run hooks after commit)
# -----------------

def post_tax_reserve_entry(amount, datetime_utc: Optional[str], notes: Optional[str] = None) -> Tuple[str, List[int]]:
    entry = _build_entry(
        action="reserve_tax",
        side="debit",
        amount=amount,
        timestamp_utc=datetime_utc,
        account_code="tax_reserve",
        strategy="TAX_RESERVE",
        tags=["tax", "reserve"],
        notes=notes,
    )
    gid, entries = propagate_group_id([entry], group_id=str(uuid.uuid4()))
    inserted_ids = post_ledger_entries_double_entry(entries, group_id=gid)
    _run_post_commit_hooks(gid, inserted_ids, as_of_utc=datetime_utc)
    return gid, inserted_ids


def post_payroll_reserve_entry(amount, datetime_utc: Optional[str], notes: Optional[str] = None) -> Tuple[str, List[int]]:
    entry = _build_entry(
        action="reserve_payroll",
        side="debit",
        amount=amount,
        timestamp_utc=datetime_utc,
        account_code="payroll_reserve",
        strategy="PAYROLL_RESERVE",
        tags=["payroll", "reserve"],
        notes=notes,
    )
    gid, entries = propagate_group_id([entry], group_id=str(uuid.uuid4()))
    inserted_ids = post_ledger_entries_double_entry(entries, group_id=gid)
    _run_post_commit_hooks(gid, inserted_ids, as_of_utc=datetime_utc)
    return gid, inserted_ids


def post_float_allocation_entry(amount, datetime_utc: Optional[str], notes: Optional[str] = None) -> Tuple[str, List[int]]:
    entry = _build_entry(
        action="float_allocation",
        side="debit",
        amount=amount,
        timestamp_utc=datetime_utc,
        account_code="float_ledger",
        strategy="FLOAT_ALLOCATION",
        tags=["float", "allocation"],
        notes=notes,
    )
    gid, entries = propagate_group_id([entry], group_id=str(uuid.uuid4()))
    inserted_ids = post_ledger_entries_double_entry(entries, group_id=gid)
    _run_post_commit_hooks(gid, inserted_ids, as_of_utc=datetime_utc)
    return gid, inserted_ids


def post_rebalance_entry(symbol: str, amount, action: str, datetime_utc: Optional[str], notes: Optional[str] = None) -> Tuple[str, List[int]]:
    entry = _build_entry(
        action=f"rebalance_{action}",
        side="debit",
        amount=amount,
        timestamp_utc=datetime_utc,
        account_code="equity",
        strategy="REBALANCE",
        tags=["rebalance", action],
        notes=notes,
        symbol=symbol,
    )
    gid, entries = propagate_group_id([entry], group_id=str(uuid.uuid4()))
    inserted_ids = post_ledger_entries_double_entry(entries, group_id=gid)
    _run_post_commit_hooks(gid, inserted_ids, as_of_utc=datetime_utc)
    return gid, inserted_ids
