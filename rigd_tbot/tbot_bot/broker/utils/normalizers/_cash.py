# tbot_bot/broker/utils/normalizers/_cash.py
# Cash/activity normalization core — ZERO I/O.
# Handles dividends/interest/fees/transfers using shared helpers.

from __future__ import annotations

from typing import Any, Dict, Optional
from decimal import Decimal

from ._common import (
    sanitize_qty,
    sanitize_price,
    sanitize_money,
    to_utc_iso,
    trntype_for_cash,
    fitid_hash,
    uuid5_deterministic,
)


def _get(raw: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    return default


def normalize_cash_core(raw: Dict[str, Any], BOT_IDENTITY: Dict[str, str]) -> Dict[str, Any]:
    # Inputs
    symbol = _get(raw, "symbol")
    activity_type: Optional[str] = _get(raw, "activity_type", "action", "type")
    qty_dec: Decimal = sanitize_qty(_get(raw, "quantity", "qty", default=0))
    price_dec: Decimal = sanitize_price(_get(raw, "price", default=0))
    fee_dec: Decimal = sanitize_money(_get(raw, "fee", default=0))
    comm_dec: Decimal = sanitize_money(_get(raw, "commission", default=0))
    amount_dec: Decimal = sanitize_money(_get(raw, "amount", default=(qty_dec * price_dec)))
    dt_utc = to_utc_iso(_get(raw, "DTPOSTED", "datetime_utc", "transaction_time", "date", "post_date"))

    # Identity/IDs
    broker_code = (BOT_IDENTITY or {}).get("BROKER_CODE", "UNKNOWN")
    activity_id = _get(raw, "activity_id", "id")
    stable = _get(raw, "stable_id") or fitid_hash(
        broker_code, "ACT", activity_type, activity_id, dt_utc, str(amount_dec)
    )
    fitid = fitid_hash("ACT", stable)
    group_seed = activity_type or "UNKNOWN"
    group_id = uuid5_deterministic("ACT", group_seed, activity_id or stable)

    # OFX
    trntype = trntype_for_cash(activity_type)

    out: Dict[str, Any] = {
        # OFX-aligned core
        "TRNTYPE": trntype,
        "DTPOSTED": dt_utc,
        "FITID": fitid,
        "group_id": group_id,
        # Canonical economics
        "symbol": symbol,
        "activity_type": activity_type,
        "quantity": float(qty_dec),
        "price": float(price_dec),
        "amount": float(amount_dec),
        "fee": float(fee_dec),
        "commission": float(comm_dec),
        # Status/meta
        "status": _get(raw, "status"),
        "description": _get(raw, "description"),
        "json_metadata": {
            "raw_broker": raw,
            "stable_id": stable,
        },
        # Identity tags
        "entity_code": (BOT_IDENTITY or {}).get("ENTITY_CODE", "UNKNOWN"),
        "jurisdiction_code": (BOT_IDENTITY or {}).get("JURISDICTION_CODE", "UNKNOWN"),
        "broker_code": broker_code,
        "bot_id": (BOT_IDENTITY or {}).get("BOT_ID", "UNKNOWN"),
    }

    return out


__all__ = ["normalize_cash_core"]
