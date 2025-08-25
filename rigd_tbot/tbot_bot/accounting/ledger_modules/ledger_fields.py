# tbot_bot/accounting/ledger_modules/ledger_fields.py

"""
Canonical ledger field definitions (v048)

This module defines:
- TRADES_FIELDS: ordered column list (must match DB schema order; 'id' omitted)
- REQUIRED_TRADES_FIELDS: minimal required set
- FIELD_SPECS: type/nullability hints for validators
- Validators: validate_trade_fields(entry) -> (ok, errors[list[str]])
- Helpers: ordered_values(entry) -> tuple aligned with TRADES_FIELDS

Notes
- OFX-aligned identifiers/fields are `TRNTYPE`, `DTPOSTED` (UTC ISO-8601 '...Z'), and `FITID` (TEXT UNIQUE).
- All timestamps are UTC ISO-8601 strings.
- Amount fields are Decimal/real-like values; sign convention enforced elsewhere.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Tuple

# ---------------------------
# Canonical ordered columns (exact DB column order)
# ---------------------------
TRADES_FIELDS: List[str] = [
    # --- OFX-aligned core identifiers ---
    "TRNTYPE",              # TEXT NOT NULL (e.g., BUY/SELL/OTHER)
    "DTPOSTED",             # ISO-8601 UTC '...Z' (NOT NULL)
    "FITID",                # TEXT UNIQUE NOT NULL
    "group_id",             # TEXT (deterministic UUIDv5 from FITIDs/group seed)

    # --- identity tags ---
    "entity_code",          # TEXT NOT NULL
    "jurisdiction_code",    # TEXT NOT NULL
    "broker_code",          # TEXT NOT NULL
    "bot_id",               # TEXT NOT NULL

    # --- business semantics ---
    "action",               # TEXT (normalized action: long/short/assignment/...)
    "side",                 # TEXT (debit|credit) - sign rules enforced elsewhere
    "symbol",               # TEXT
    "quantity",             # REAL/NUMERIC
    "price",                # REAL/NUMERIC
    "total_value",          # REAL/NUMERIC NOT NULL (sign by side)
    "amount",               # REAL/NUMERIC (optional, mirrors economics)
    "commission",           # REAL/NUMERIC
    "fee",                  # REAL/NUMERIC
    "currency",             # TEXT (ISO 4217-like, 3-4 letters)
    "account",              # TEXT NOT NULL (COA path)
    "trade_id",             # TEXT
    "strategy",             # TEXT
    "tags",                 # TEXT (JSON array)
    "description",          # TEXT
    "status",               # TEXT (ok/rejected/...)
    "approval_status",      # TEXT (approved/pending/...)
    "created_by",           # TEXT
    "updated_by",           # TEXT
    "response_hash",        # TEXT (blake/sha hash of API response)
    "sync_run_id",          # TEXT
    "json_metadata",        # TEXT (JSON blob)

    # --- metadata times (managed by DB or app) ---
    "created_at_utc",       # ISO-8601 (UTC)
    "updated_at_utc",       # ISO-8601 (UTC)
]

# Minimal required set for inserts (DB may also enforce NOT NULL)
REQUIRED_TRADES_FIELDS = {
    "TRNTYPE",
    "DTPOSTED",
    "FITID",
    "entity_code",
    "jurisdiction_code",
    "broker_code",
    "bot_id",
    "account",
    "total_value",
}

# Type/nullability hints for validation (informational; DB is source of truth)
FIELD_SPECS: Dict[str, Dict[str, Any]] = {
    "TRNTYPE": {"type": "enum_trntype", "nullable": False},
    "DTPOSTED": {"type": "iso_utc", "nullable": False},
    "FITID": {"type": "text", "nullable": False},
    "group_id": {"type": "text", "nullable": True},

    "entity_code": {"type": "text", "nullable": False},
    "jurisdiction_code": {"type": "text", "nullable": False},
    "broker_code": {"type": "text", "nullable": False},
    "bot_id": {"type": "text", "nullable": False},

    "action": {"type": "enum_action", "nullable": True},
    "side": {"type": "enum_side", "nullable": True},
    "symbol": {"type": "text", "nullable": True},
    "quantity": {"type": "number", "nullable": True},
    "price": {"type": "number", "nullable": True},
    "total_value": {"type": "number", "nullable": False},
    "amount": {"type": "number", "nullable": True},
    "commission": {"type": "number", "nullable": True},
    "fee": {"type": "number", "nullable": True},
    "currency": {"type": "currency", "nullable": True},
    "account": {"type": "text", "nullable": False},
    "trade_id": {"type": "text", "nullable": True},
    "strategy": {"type": "text", "nullable": True},
    "tags": {"type": "json_text", "nullable": True},
    "description": {"type": "text", "nullable": True},
    "status": {"type": "text", "nullable": True},
    "approval_status": {"type": "text", "nullable": True},
    "created_by": {"type": "text", "nullable": True},
    "updated_by": {"type": "text", "nullable": True},
    "response_hash": {"type": "text", "nullable": True},
    "sync_run_id": {"type": "text", "nullable": True},
    "json_metadata": {"type": "json_text", "nullable": True},
    "created_at_utc": {"type": "iso_utc", "nullable": True},
    "updated_at_utc": {"type": "iso_utc", "nullable": True},
}

# Allowed values (OFX-normalized TRNTYPE set + internal)
ALLOWED_TRNTYPE = [
    "BUY", "SELL", "DIV", "INT", "FEE", "XFER", "WITHDRAWAL", "DEPOSIT", "OTHER", "POS"
]
ALLOWED_TRADE_ACTIONS = [
    "long", "short", "put", "call", "assignment", "exercise", "expire", "reorg", "inverse", "other"
]
ALLOWED_SIDES = ["debit", "credit"]

_CURRENCY_RE = re.compile(r"^[A-Z]{3,4}$")


def _is_iso_utc(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return False
        return dt.astimezone(timezone.utc).tzinfo == timezone.utc
    except Exception:
        return False


def _is_number(x: Any) -> bool:
    try:
        Decimal(str(x))
        return True
    except (InvalidOperation, ValueError, TypeError):
        return False


def _is_json_text(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, str):
        if not x.strip():
            return True
        try:
            json.loads(x)
            return True
        except Exception:
            return False
    # dict/list should be serialized by callers before insert
    return False


def validate_trade_fields(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate presence, basic typing, and enum ranges for a single trade row (dict).
    Returns (ok, errors[list[str]]).
    """
    errors: List[str] = []

    # Required presence
    for k in REQUIRED_TRADES_FIELDS:
        if entry.get(k) in (None, ""):
            errors.append(f"missing_required:{k}")

    # Types / enums
    for k, spec in FIELD_SPECS.items():
        v = entry.get(k)
        if v in (None, ""):
            if not spec["nullable"]:
                errors.append(f"null_not_allowed:{k}")
            continue

        t = spec["type"]
        if t == "iso_utc" and not _is_iso_utc(v):
            errors.append(f"invalid_iso_utc:{k}")
        elif t == "number" and not _is_number(v):
            errors.append(f"invalid_number:{k}")
        elif t == "currency" and not (isinstance(v, str) and _CURRENCY_RE.match(v)):
            errors.append(f"invalid_currency:{k}")
        elif t == "enum_side" and str(v).lower() not in ALLOWED_SIDES:
            errors.append(f"invalid_side:{v}")
        elif t == "enum_action" and str(v).lower() not in ALLOWED_TRADE_ACTIONS:
            errors.append(f"invalid_action:{v}")
        elif t == "enum_trntype" and str(v).upper() not in ALLOWED_TRNTYPE:
            errors.append(f"invalid_trntype:{v}")
        elif t == "json_text" and not _is_json_text(v):
            errors.append(f"invalid_json_text:{k}")

    # Account non-empty sanity
    acct = str(entry.get("account") or "").strip()
    if not acct or (acct.startswith("Uncategorized") and "allow_uncategorized" not in entry):
        errors.append("invalid_account:empty_or_uncategorized")

    return (len(errors) == 0), errors


def ordered_values(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    """
    Return values aligned with TRADES_FIELDS order (missing → None).
    Useful for parameterized INSERTs.
    """
    return tuple(entry.get(k) for k in TRADES_FIELDS)


# Backwards compatibility constants (kept for imports; not authoritative)
LEDGER_ENTRIES_FIELDS = TRADES_FIELDS  # use trades layout for legacy helpers
RECONCILIATION_LOG_FIELDS = [
    "id",
    "trade_id",
    "entity_code",
    "jurisdiction_code",
    "broker_code",
    "broker",
    "error_code",
    "account_id",
    "statement_date",
    "ledger_balance",
    "ledger_entry_id",
    "broker_balance",
    "delta",
    "status",
    "resolution",
    "resolved_by",
    "resolved_at",
    "raw_record",
    "notes",
    "recon_type",
    "raw_record_json",
    "compare_fields",
    "json_metadata",
    "timestamp_utc",
    "sync_run_id",
    "api_hash",
    "imported_at",
    "updated_at",
    "user_action",
    "mapping_version",
]
