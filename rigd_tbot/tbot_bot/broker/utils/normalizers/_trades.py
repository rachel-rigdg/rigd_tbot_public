# tbot_bot/broker/utils/normalizers/_trades.py
# Trade normalization core — ZERO I/O.
# Maps side/action, sanitizes qty/price/fees, coerces UTC, and produces OFX-aligned fields.

from __future__ import annotations

from typing import Any, Dict, Optional
from decimal import Decimal

from ._common import (
    sanitize_qty,
    sanitize_price,
    sanitize_money,
    to_utc_iso,
    trntype_for_trade,
    fitid_hash,
    uuid5_deterministic,
)


def _get(raw: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    return default


def normalize_trade_core(raw: Dict[str, Any], BOT_IDENTITY: Dict[str, str]) -> Dict[str, Any]:
    # Inputs
    symbol = _get(raw, "symbol", "underlying")
    action_raw: Optional[str] = (_get(raw, "action", "side") or "").lower() or None
    qty_dec: Decimal = sanitize_qty(_get(raw, "quantity", "qty", "filled_qty", default=0))
    price_dec: Decimal = sanitize_price(_get(raw, "price", "filled_avg_price", "fill_price", default=0))
    fee_dec: Decimal = sanitize_money(_get(raw, "fee", default=0))
    comm_dec: Decimal = sanitize_money(_get(raw, "commission", default=0))
    dt_utc = to_utc_iso(_get(raw, "DTPOSTED", "datetime_utc", "filled_at", "transaction_time", "submitted_at"))

    # Economics
    total_value_dec: Decimal = (qty_dec * price_dec).quantize(sanitize_money(0))

    # Identity/IDs
    broker_code = (BOT_IDENTITY or {}).get("BROKER_CODE", "UNKNOWN")
    trade_id = _get(raw, "trade_id", "order_id", "id")
    stable = _get(raw, "stable_id") or fitid_hash(broker_code, "TRD", trade_id, symbol, dt_utc, str(qty_dec), str(price_dec))
    fitid = fitid_hash("TRD", stable)
    group_seed = _get(raw, "order_id") or stable or fitid

    # OFX
    trntype = trntype_for_trade(action_raw)

    out: Dict[str, Any] = {
        # OFX-aligned core
        "TRNTYPE": trntype,
        "DTPOSTED": dt_utc,
        "FITID": fitid,
        "group_id": uuid5_deterministic("TRD", group_seed),
        # Canonical trade economics
        "symbol": symbol,
        "action": action_raw,
        "quantity": float(qty_dec),
        "price": float(price_dec),
        "total_value": float(total_value_dec),
        "fee": float(fee_dec),
        "commission": float(comm_dec),
        # Status/meta
        "status": _get(raw, "status", "order_status"),
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


__all__ = ["normalize_trade_core"]
