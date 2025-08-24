# tbot_bot/accounting/ledger_modules/ledger_entry.py

"""
Legacy single-entry ledger helpers.
All new posting/editing/deleting must use double-entry and helpers in ledger_double_entry.py / ledger_edit.py.

This module now provides a canonical normalizer for single entries:
- build_normalized_entry(): fitid, strategy, tags, identity fields, response_hash, sync_run_id, UTC ISO-8601
- Decimal validation/normalization for numeric amounts; currency/account sanity checks
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from typing import Any, Dict, List, Optional

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS

# ---- Compliance (prefer v048 API) ----
try:
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import validate_entries as _validate_entries  # type: ignore

    def _is_compliant(entry: dict) -> bool:
        ok, _ = _validate_entries([entry])
        return bool(ok)
except Exception:
    try:
        from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import compliance_filter_ledger_entry as _legacy_filter  # type: ignore

        def _is_compliant(entry: dict) -> bool:
            res = _legacy_filter(entry)
            if isinstance(res, tuple):
                return bool(res[0])
            return res is not None
    except Exception:
        def _is_compliant(entry: dict) -> bool:  # type: ignore
            return True

# Decimal policy
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN
_Q = Decimal("0.0001")


# -----------------------
# Identity helpers
# -----------------------

def get_identity_tuple():
    """
    Returns (entity_code, jurisdiction_code, broker_code, bot_id) from env-backed identity.
    """
    parts = str(get_bot_identity()).split("_")
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])


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
      - fitid (TEXT UNIQUE), strategy, tags (JSON string), entity_code, jurisdiction_code,
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

    # Strategy / tags
    if "strategy" not in e or e.get("strategy") in (None, ""):
        e["strategy"] = "unspecified"
    tags = e.get("tags")
    if isinstance(tags, (list, dict)):
        e["tags"] = json.dumps(tags, default=str)
    elif isinstance(tags, str) and tags.strip().startswith("["):
        # keep as-is JSON string
        e["tags"] = tags
    else:
        # comma-separated or None → store as JSON array for consistency
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
        # Compute if quantity/price present; subtract fees/commission if provided
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

    # amount column mirrors magnitude with sign by side if used elsewhere
    e["amount"] = float(total)

    # Account
    e["account"] = _norm_account(e.get("account"), side)

    # FITID: set only if available (fitid|trade_id|order_id); otherwise leave NULL
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


# -----------------------
# Legacy helpers (DB I/O)
# -----------------------

def load_internal_ledger():
    """
    Load raw trades rows as list of dicts.
    """
    db_path = resolve_ledger_db_path(*get_identity_tuple())
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query = "SELECT id, " + ", ".join(TRADES_FIELDS) + " FROM trades"
    cursor = conn.execute(query)
    results: List[Dict[str, Any]] = [{k: row[k] for k in row.keys()} for row in cursor.fetchall()]
    conn.close()
    return results


def mark_entry_resolved(entry_id):
    """
    Mark an entry as approved/resolved. (Legacy UI interaction)
    """
    db_path = resolve_ledger_db_path(*get_identity_tuple())
    # Lazy import to avoid hard dependency if web layer is absent
    try:
        from tbot_web.support.auth_web import get_current_user  # type: ignore
        current_user = get_current_user()
        updater = current_user.username if hasattr(current_user, "username") else (current_user or "system")
    except Exception:
        updater = "system"
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE trades SET approval_status = 'approved', updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (updater, entry_id),
    )
    conn.commit()
    conn.close()


def add_ledger_entry(entry_data):
    """
    Legacy single-entry ledger posting.
    Use post_ledger_entries_double_entry for all new entries.
    """
    if not isinstance(entry_data, dict):
        return
    normalized = build_normalized_entry(entry_data)
    if not _is_compliant(normalized):
        return
    db_path = resolve_ledger_db_path(*get_identity_tuple())
    cols = TRADES_FIELDS
    placeholders = ", ".join("?" for _ in cols)
    values = [normalized.get(c) for c in cols]
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute(f"INSERT INTO trades ({', '.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()
