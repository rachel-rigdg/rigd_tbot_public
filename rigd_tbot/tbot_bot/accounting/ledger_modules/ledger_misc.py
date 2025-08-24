# tbot_bot/accounting/ledger_modules/ledger_misc.py

"""
Shared ledger utilities (v048)
- Decimal context & rounding policies
- Currency helpers
- Safe dict ops
- Sign conventions
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

# ---------------------------
# Decimal policy / constants
# ---------------------------

getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN

DEC_QUANT = Decimal("0.0001")
SIDE_DEBIT = "debit"
SIDE_CREDIT = "credit"
CURRENCY_DEFAULT = "USD"

# Sign convention:
# - Debits are positive (+)
# - Credits are negative (−)
DEBIT_SIGN = Decimal("+1")
CREDIT_SIGN = Decimal("-1")


# ---------------------------
# Time helpers
# ---------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------
# Decimal helpers
# ---------------------------

def to_dec(val: Any, *, allow_none: bool = False, quant: Decimal = DEC_QUANT) -> Optional[Decimal]:
    if val is None:
        return None if allow_none else Decimal("0").quantize(quant)
    if isinstance(val, Decimal):
        return val.quantize(quant)
    try:
        return Decimal(str(val)).quantize(quant)
    except Exception:
        return None if allow_none else Decimal("0").quantize(quant)


def sum_dec(values: Iterable[Any], *, quant: Decimal = DEC_QUANT) -> Decimal:
    total = Decimal("0")
    for v in values:
        dv = to_dec(v, quant=quant)
        total += dv if dv is not None else Decimal("0")
    return total.quantize(quant)


def ensure_side_sign(amount: Any, side: str, *, quant: Decimal = DEC_QUANT) -> Decimal:
    """
    Normalize amount sign per side policy:
      - debit → positive
      - credit → negative
    """
    amt = to_dec(amount, quant=quant)
    if side and str(side).lower() == SIDE_CREDIT:
        return (-abs(amt)).quantize(quant)
    return abs(amt).quantize(quant)


# ---------------------------
# Currency helpers
# ---------------------------

def normalize_currency(code: Optional[str]) -> str:
    if not code:
        return CURRENCY_DEFAULT
    s = str(code).strip().upper()
    if 3 <= len(s) <= 4 and s.isalpha():
        return s
    return CURRENCY_DEFAULT


def money_tuple(amount: Any, currency: Optional[str] = None) -> Tuple[Decimal, str]:
    return to_dec(amount), normalize_currency(currency)


# ---------------------------
# Safe dict ops
# ---------------------------

def coalesce(*vals: Any) -> Any:
    for v in vals:
        if v is not None and v != "":
            return v
    return None


def get_in(d: Dict[str, Any], path: Union[str, Sequence[Union[str, int]]], default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    keys: List[Union[str, int]]
    if isinstance(path, str):
        keys = [p if not p.isdigit() else int(p) for p in path.split(".") if p != ""]
    else:
        keys = list(path)
    cur: Any = d
    for k in keys:
        try:
            if isinstance(k, int) and isinstance(cur, list):
                cur = cur[k]
            elif isinstance(cur, dict):
                cur = cur.get(k)  # type: ignore[arg-type]
            else:
                return default
        except Exception:
            return default
        if cur is None:
            return default
    return cur


def setdefault_json(d: Dict[str, Any], key: str, default_obj: Union[Dict, List]) -> Dict[str, Any]:
    """
    Ensure d[key] is a JSON-serializable object (dict/list). Converts JSON string to object if needed.
    """
    val = d.get(key)
    if isinstance(val, (dict, list)):
        return d
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            if isinstance(parsed, (dict, list)):
                d[key] = parsed
                return d
        except Exception:
            pass
    d[key] = default_obj
    return d


# ---------------------------
# COA account helpers
# ---------------------------

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"


def _ledger_dsn() -> str:
    parts = str(get_bot_identity()).split("_")
    if len(parts) < 4:
        raise ValueError("Invalid BOT identity; expected 'ENTITY_JURISDICTION_BROKER_BOTID'")
    ec, jc, bc, bid = parts[0], parts[1], parts[2], parts[3]
    return str(resolve_ledger_db_path(ec, jc, bc, bid))


def get_coa_accounts() -> List[Tuple[str, str]]:
    """
    Return list of (code, name) from COA accounts.
    Tries structured columns first, falls back to JSON column layout.
    """
    if TEST_MODE_FLAG.exists():
        return []
    dsn = _ledger_dsn()
    with sqlite3.connect(dsn) as conn:
        try:
            rows = conn.execute("SELECT code, name FROM coa_accounts").fetchall()
            accounts = [(r[0], r[1]) for r in rows if r and r[0] and r[1]]
        except sqlite3.Error:
            # Fallback: JSON column "account_json" with keys {code,name}
            try:
                rows = conn.execute(
                    "SELECT json_extract(account_json, '$.code'), json_extract(account_json, '$.name') FROM coa_accounts"
                ).fetchall()
                accounts = [(r[0], r[1]) for r in rows if r and r[0] and r[1]]
            except sqlite3.Error:
                accounts = []
    # Sort by name for UI friendliness
    return sorted(accounts, key=lambda x: str(x[1]))
