# tbot_bot/accounting/ledger_modules/ledger_entry.py

"""
Legacy single-entry ledger helpers (normalized builder only; no direct writes).
All new posting/editing/deleting must use double-entry and helpers in ledger_double_entry.py / ledger_edit.py.

This module now provides a canonical normalizer for single entries:
- build_normalized_entry(): FITID, DTPOSTED (UTC ISO), strategy, tags, identity fields,
  response_hash, sync_run_id, UTC ISO-8601
- Decimal validation/normalization for numeric amounts; currency/account sanity checks
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from typing import Any, Dict, Optional, Tuple

from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS

# Decimal policy
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN
_Q = Decimal("0.0001")


# -----------------------
# Identity helpers
# -----------------------

def get_identity_tuple() -> Tuple[str, str, str, str]:
    """
    Returns (entity_code, jurisdiction_code, broker_code, bot_id) from env-backed identity.
    """
    parts = str(get_bot_identity()).split("_")
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])  # type: ignore[return-value]


# -----------------------
# Normalization utilities
# -----------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dec(val: Any, allow_none: bool = False) -> Optional[Decimal]:
    if val is None:
        return None if allow_none else Decimal("0").quantize(_Q)
    if isinstance(val, Decimal):
        return val.quantize(_Q)
    try:
        d = Decimal(str(val)).quantize(_Q)
    except Exception:
        if allow_none:
            return None
        d = Decimal("0").quantize(_Q)
    return d


def _norm_currency(code: Optional[str]) -> str:
    if not code:
        return "USD"
    s = str(code).strip().upper()
    return s if 2 < len(s) < 5 else "USD"


def _norm_account(path: Optional[str], side: Optional[str]) -> str:
    s = (path or "").strip()
    if not s:
        return "Uncategorized:Credit" if str(side).lower() == "credit" else "Uncategorized:Debit"
    return s


def _ensure_iso_utc(ts: Optional[str]) -> str:
    if not ts:
        return _utc_now_iso()
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return _utc_now_iso()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _hash_response(payload: Any) -> Optional[str]:
    if payload is None:
        return None
    try:
        data = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.blake2s(data).hexdigest()
    except Exception:
        return None


def _coalesce(*vals):
    for v in vals:
        if v is not None and v != "":
            return v
    return None


# -----------------------
# Public: normalized builder
# -----------------------

def build_normalized_entry(entry_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a normalized single-entry dict aligned to TRADES_FIELDS.
    Fields:
      - fitid (TEXT UNIQUE), DTPOSTED (UTC ISO mirror of timestamp_utc),
        strategy, tags (JSON string), entity_code, jurisdiction_code,
        broker_code, bot_id, response_hash, sync_run_id, timestamp_utc (ISO-8601, tz-aware)
      - Validated/quantized Decimal amounts stored as float for SQLite binding safety.
      - Currency normalized to 3-4 uppercase letters; account code non-empty.
    """
    ec, jc, bc, bid = get_identity_tuple()

    e = dict(entry_data) if isinstance(entry_data, dict) else {}

    # Identity & metadata
    e["entity_code"] = ec
    e["jurisdiction_code"] = jc
    e["broker_code"] = bc
    e["bot_id"] = bid

    # Timestamp: ALWAYS tz-aware UTC
    e["timestamp_utc"] = _ensure_iso_utc(_coalesce(e.get("timestamp_utc"), e.get("datetime_utc"), e.get("created_at_utc")))
    # OFX mirror
    e["DTPOSTED"] = e["timestamp_utc"]

    # Strategy / tags
    if "strategy" not in e or e.get("strategy") in (None, ""):
        e["strategy"] = "unspecified"
    tags = e.get("tags")
    if isinstance(tags, (list, dict)):
        e["tags"] = json.dumps(tags, default=str)
    elif isinstance(tags, str) and tags.strip().startswith("["):
        e["tags"] = tags
    else:
        if isinstance(tags, str) and tags.strip():
            e["tags"] = json.dumps([t.strip() for t in tags.split(",") if t.strip()])
        else:
            e["tags"] = json.dumps([])

    # Currency
    e["currency"] = _norm_currency(e.get("currency"))

    # Side default
    side = str(e.get("side") or "").lower()
    if side not in ("debit", "credit"):
        side = "debit"
        e["side"] = side

    # Amounts (Decimal → float for sqlite)
    qty = _to_dec(e.get("quantity"), allow_none=True)
    price = _to_dec(e.get("price"), allow_none=True)
    fee = _to_dec(e.get("fee"), allow_none=True) or Decimal("0").quantize(_Q)
    commission = _to_dec(e.get("commission"), allow_none=True) or Decimal("0").quantize(_Q)

    if "total_value" in e and e.get("total_value") is not None:
        total = _to_dec(e.get("total_value"))
    else:
        if qty is not None and price is not None:
            gross = (qty * price).quantize(_Q)
        else:
            gross = Decimal("0").quantize(_Q)
        total = (gross - fee - commission).quantize(_Q)

    # Ensure sign aligns with side: debit positive, credit negative
    if side == "credit" and total > 0:
        total = -total
    if side == "debit" and total < 0:
        total = -total
    e["total_value"] = float(total)
    e["amount"] = float(total)  # mirror

    # Account
    e["account"] = _norm_account(e.get("account"), side)

    # FITID: prefer provided stable id (fitid|trade_id|order_id)
    provided_fitid = _coalesce(e.get("fitid"), e.get("trade_id"), e.get("order_id"))
    e["fitid"] = str(provided_fitid) if provided_fitid not in (None, "") else None

    # Response hash (API response/confirmations)
    e["response_hash"] = _hash_response(_coalesce(e.get("response"), e.get("api_response"), e.get("broker_response")))

    # Sync run id (optional)
    e["sync_run_id"] = _coalesce(e.get("sync_run_id"), e.get("sync_id"))

    # Ensure all schema fields exist
    for k in TRADES_FIELDS:
        e.setdefault(k, None)

    # JSON-encode complex types to text for SQLite safety
    for k, v in list(e.items()):
        if isinstance(v, (dict, list)):
            e[k] = json.dumps(v, default=str)

    return e


__all__ = ["build_normalized_entry", "get_identity_tuple"]
