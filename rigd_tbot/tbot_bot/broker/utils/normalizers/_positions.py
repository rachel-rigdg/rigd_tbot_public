# tbot_bot/broker/utils/normalizers/_positions.py
# Position normalization core — ZERO I/O.
# Produces opening position snapshots with OFX-aligned fields.

from __future__ import annotations

from typing import Any, Dict, Optional
from decimal import Decimal

from ._common import (
    sanitize_qty,
    sanitize_price,
    sanitize_money,
    to_utc_iso,
    fitid_hash,
    uuid5_deterministic,
)


def _get(raw: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    return default


def normalize_position_core(raw: Dict[str, Any], BOT_IDENTITY: Dict[str, str]) -> Dict[str, Any]:
    # Inputs
    symbol = _get(raw, "symbol")
    qty_dec: Decimal = sanitize_qty(_get(raw, "qty", "quantity", default=0))
    avg_dec: Decimal = sanitize_price(_get(raw, "avg_entry_price", "avg_price", default=0))
    mv_dec: Decimal = sanitize_money(_get(raw, "market_value", default=(qty_dec * avg_dec)))
    basis_dec: Decimal = sanitize_money(_get(raw, "cost_basis", default=(qty_dec * avg_dec)))
    dt_utc = to_utc_iso(_get(raw, "DTPOSTED", "datetime_utc", "updated_at", "timestamp"))

    # Identity/IDs
    broker_code = (BOT_IDENTITY or {}).get("BROKER_CODE", "UNKNOWN")
    position_id = _get(raw, "position_id", "asset_id", default=symbol)
    stable = _get(raw, "stable_id") or fitid_hash(broker_code, "POS", position_id, symbol, str(qty_dec), str(avg_dec))
    fitid = fitid_hash("POS", stable)
    group_id = uuid5_deterministic("POS", symbol or "UNKNOWN")

    out: Dict[str, Any] = {
        # OFX-aligned core
        "TRNTYPE": "POS",
        "DTPOSTED": dt_utc,
        "FITID": fitid,
        "group_id": group_id,
        # Canonical position economics
        "symbol": symbol,
        "qty": float(qty_dec),
        "avg_entry_price": float(avg_dec),
        "market_value": float(mv_dec),
        "cost_basis": float(basis_dec),
        # Meta
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


__all__ = ["normalize_position_core"]
