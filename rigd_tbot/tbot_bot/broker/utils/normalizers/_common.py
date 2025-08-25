# tbot_bot/broker/utils/normalizers/_common.py
# Shared helpers for broker normalizers: enums/maps, Decimal sanitizers, UTC coercion, FITID hashing.
# ZERO I/O. Pure functions only.

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal, ROUND_HALF_EVEN, InvalidOperation, getcontext
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------
# Decimal / Quantization
# ---------------------------

getcontext().prec = 28  # high precision for intermediate math
ROUNDING = ROUND_HALF_EVEN

MONEY_EXP = Decimal("0.01")         # cents
PRICE_EXP = Decimal("0.000001")     # 1e-6
QTY_EXP = Decimal("0.00000001")     # 1e-8


def to_decimal(value: Any) -> Decimal:
    """Best-effort Decimal conversion. Invalid -> Decimal('0')."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        # str() avoids binary float artifacts
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def to_decimal_or_none(value: Any) -> Optional[Decimal]:
    """Return Decimal or None if invalid/empty."""
    if value in (None, "", b""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def quantize_decimal(value: Any, exp: Decimal) -> Decimal:
    """Quantize to exp with banker's rounding."""
    d = to_decimal(value)
    return d.quantize(exp, rounding=ROUNDING)


def sanitize_money(value: Any) -> Decimal:
    return quantize_decimal(value, MONEY_EXP)


def sanitize_price(value: Any) -> Decimal:
    return quantize_decimal(value, PRICE_EXP)


def sanitize_qty(value: Any) -> Decimal:
    return quantize_decimal(value, QTY_EXP)


# ---------------------------
# UTC helpers
# ---------------------------

def parse_to_utc(dt: Any) -> Optional[datetime]:
    """Parse str/datetime to timezone-aware UTC datetime. Invalid -> None."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(dt, str):
        s = dt.strip()
        try:
            s = s.replace("Z", "+00:00") if "Z" in s else s
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def to_utc_iso(dt: Any, *, milliseconds: bool = True) -> Optional[str]:
    """Return ISO-8601 '...Z' or None."""
    p = parse_to_utc(dt)
    if p is None:
        return None
    if milliseconds:
        return p.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return p.isoformat().replace("+00:00", "Z")


# ---------------------------
# OFX / TRNTYPE maps
# ---------------------------

OFX_TRADE_TRNTYPE_MAP = {
    "buy": "BUY",
    "long": "BUY",
    "sell": "SELL",
    "short": "SELL",
    "assignment": "TRANSFER",
    "exercise": "TRANSFER",
    "put": "OTHER",
    "call": "OTHER",
    "expire": "OTHER",
    "reorg": "OTHER",
    "inverse": "OTHER",
}

OFX_CASH_TRNTYPE_MAP = {
    "DIV": "DIV",
    "INT": "INT",
    "FEE": "FEE",
    "TRANS": "XFER",
    "JOURNAL": "XFER",
    "WITHDRAWAL": "WITHDRAWAL",
    "DEPOSIT": "DEPOSIT",
}


def trntype_for_trade(action: Optional[str]) -> str:
    a = (action or "").lower()
    return OFX_TRADE_TRNTYPE_MAP.get(a, "OTHER")


def trntype_for_cash(activity_type: Optional[str]) -> str:
    a = (activity_type or "").upper()
    return OFX_CASH_TRNTYPE_MAP.get(a, "OTHER")


# ---------------------------
# Deterministic IDs
# ---------------------------

_UUID_NS = uuid.UUID("76b5c9f8-bf65-4b6a-9d93-2f7b0b5d7a44")  # fixed namespace


def fitid_hash(*parts: Any) -> str:
    """Deterministic SHA-1 hex over joined parts."""
    buf = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(buf.encode("utf-8")).hexdigest()


def uuid5_deterministic(*parts: Any) -> str:
    """Deterministic UUIDv5 over joined parts using fixed namespace."""
    name = "|".join("" if p is None else str(p) for p in parts)
    return str(uuid.uuid5(_UUID_NS, name))


__all__ = [
    # decimal
    "ROUNDING",
    "MONEY_EXP",
    "PRICE_EXP",
    "QTY_EXP",
    "to_decimal",
    "to_decimal_or_none",
    "quantize_decimal",
    "sanitize_money",
    "sanitize_price",
    "sanitize_qty",
    # time
    "parse_to_utc",
    "to_utc_iso",
    # OFX
    "OFX_TRADE_TRNTYPE_MAP",
    "OFX_CASH_TRNTYPE_MAP",
    "trntype_for_trade",
    "trntype_for_cash",
    # ids
    "fitid_hash",
    "uuid5_deterministic",
]
