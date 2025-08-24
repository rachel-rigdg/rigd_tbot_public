# tbot_bot/accounting/ledger_modules/ledger_compliance_filter.py
"""
Ledger compliance filter for validating entries before they are written to the ledger.

Requirements (v048):
- Pre-write validation: required fields, sane values, date window, mapping exists.
- Returns (ok, errors); on failure → audit a reject event; NEVER mutate payload.

This module exposes:
- validate_entries(entries) -> (ok: bool, errors: list[str])
- validate(batch) and validate_batch(entries) aliases
- Back-compat helpers: is_compliant_ledger_entry, compliance_filter_ledger_entry, filter_valid_entries
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_audit import log_audit_event

# Optional mapping check (no mutation) to verify mapping exists when account is absent
try:
    from tbot_bot.accounting.ledger_modules.ledger_account_map import map_transaction_to_accounts  # type: ignore
except Exception:  # pragma: no cover
    map_transaction_to_accounts = None  # type: ignore

# -----------------
# Config (env-only)
# -----------------
_MAX_ABS_AMOUNT = Decimal(os.getenv("LEDGER_MAX_ABS_AMOUNT", "100000000"))  # 100M default
_ENFORCE_WINDOW = os.getenv("LEDGER_ENFORCE_DATE_WINDOW", "1") == "1"
_MAX_BACK_DAYS = int(os.getenv("LEDGER_MAX_BACKDATE_DAYS", "14"))
_MAX_FUTURE_MIN = int(os.getenv("LEDGER_MAX_FUTURE_MINUTES", "10"))

# -----------------
# Helpers
# -----------------

_TS_KEYS = ("timestamp_utc", "datetime_utc", "created_at_utc")


def _to_decimal(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    try:
        d = Decimal(str(val))
    except (InvalidOperation, ValueError):
        return None
    if d.is_nan() or d in (Decimal("Infinity"), Decimal("-Infinity")):
        return None
    return d


def _parse_utc(ts_val: Any) -> Optional[datetime]:
    if ts_val is None:
        return None
    if isinstance(ts_val, datetime):
        dt = ts_val
    elif isinstance(ts_val, str):
        try:
            dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
        except Exception:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _find_timestamp(entry: Dict[str, Any]) -> Optional[datetime]:
    for k in _TS_KEYS:
        dt = _parse_utc(entry.get(k))
        if dt is not None:
            return dt
    return None


def _has_account(entry: Dict[str, Any]) -> bool:
    acct = str(entry.get("account") or "").strip()
    return bool(acct) and not acct.startswith("Uncategorized")


def _verify_mapping_exists(entry: Dict[str, Any]) -> bool:
    if _has_account(entry):
        return True
    if map_transaction_to_accounts is None:
        return False
    # Do not mutate; just verify mapping is resolvable
    try:
        _da, _ca, _ver = map_transaction_to_accounts(
            {
                "broker": entry.get("broker"),
                "type": entry.get("type"),
                "subtype": entry.get("subtype"),
                "description": entry.get("description"),
                "code": entry.get("code"),
            }
        )
        return True
    except Exception:
        return False


def _audit_reject(entry: Dict[str, Any], reason: str) -> None:
    log_audit_event(
        action="compliance_reject",
        entry_id=entry.get("id"),
        user="system",
        before=entry,
        after=None,
        reason=reason,
        audit_reference=entry.get("audit_reference"),
        group_id=entry.get("group_id"),
        fitid=entry.get("fitid"),
        extra={"module": "ledger_compliance_filter"},
    )


# -----------------
# Core validation
# -----------------

def _validate_entry(entry: Dict[str, Any]) -> Optional[str]:
    # Type
    if not isinstance(entry, dict):
        return "not_a_dict"

    # Required basics for splits (pre-write): account, side, total_value, timestamp
    # Cash/import pre-mapping entries may not have 'account'; in such case, verify mapping resolvable.
    if not _has_account(entry):
        if not _verify_mapping_exists(entry):
            return "unmapped_or_missing_account"

    side = str(entry.get("side") or "").lower()
    if side not in ("debit", "credit"):
        return "invalid_side"

    amount = _to_decimal(entry.get("total_value"))
    if amount is None:
        return "invalid_total_value"

    if amount == 0:
        # zero-value splits are permitted only if explicitly marked fee-only or system flag says allow
        if not bool(entry.get("allow_zero_value")):
            return "zero_total_value_not_allowed"

    if abs(amount) > _MAX_ABS_AMOUNT:
        return "amount_exceeds_policy_limit"

    # Timestamp window (UTC)
    ts = _find_timestamp(entry)
    if ts is None:
        return "missing_timestamp"

    if _ENFORCE_WINDOW:
        now = datetime.now(timezone.utc)
        if ts < now - timedelta(days=_MAX_BACK_DAYS):
            return "timestamp_too_old"
        if ts > now + timedelta(minutes=_MAX_FUTURE_MIN):
            return "timestamp_in_future"

    return None


def validate_entries(entries: Iterable[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validate a batch of entries. Returns (ok, errors[list[str]]).
    On any failure, writes an audit reject event per offending entry.
    """
    errors: List[str] = []
    for e in entries:
        reason = _validate_entry(e)
        if reason:
            errors.append(reason)
            _audit_reject(e, reason)
    return (len(errors) == 0), errors


# Aliases expected by callers
def validate(batch: Iterable[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    return validate_entries(batch)


def validate_batch(entries: Iterable[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    return validate_entries(entries)


# -----------------
# Backward compatibility shims
# -----------------

def is_compliant_ledger_entry(entry: dict) -> bool:
    ok, _ = validate_entries([entry])
    return ok


def compliance_filter_ledger_entry(entry: dict):
    ok, _ = validate_entries([entry])
    return entry if ok else None


def filter_valid_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        ok, _ = validate_entries([e])
        if ok:
            out.append(e)
    return out
