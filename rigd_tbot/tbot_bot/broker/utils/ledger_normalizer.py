# tbot_bot/broker/utils/ledger_normalizer.py
# Single public API for broker→ledger normalization.
# Emits OFX-aligned dicts with strict UTC timestamps, stable FITIDs, and group_id.
# Delegates to internal normalizers when available; contains safe fallbacks. No DB I/O.

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Optional internal delegates (to be provided by tbot_bot/broker/utils/normalizers/)
try:
    from tbot_bot.broker.utils.normalizers._trades import normalize_trade_core as _trade_core  # type: ignore
    from tbot_bot.broker.utils.normalizers._cash import normalize_cash_core as _cash_core      # type: ignore
    from tbot_bot.broker.utils.normalizers._positions import normalize_position_core as _pos_core  # type: ignore
    _HAS_INTERNALS = True
except Exception:
    _HAS_INTERNALS = False

from tbot_bot.support.utils_identity import get_bot_identity


# ---------------------------
# Identity & helpers
# ---------------------------

_raw_id = get_bot_identity()
if isinstance(_raw_id, str):
    parts = _raw_id.split("_")
    BOT_IDENTITY = {
        "ENTITY_CODE": parts[0] if len(parts) > 0 else "UNKNOWN",
        "JURISDICTION_CODE": parts[1] if len(parts) > 1 else "UNKNOWN",
        "BROKER_CODE": parts[2] if len(parts) > 2 else "UNKNOWN",
        "BOT_ID": parts[3] if len(parts) > 3 else "UNKNOWN",
    }
elif isinstance(_raw_id, dict):
    BOT_IDENTITY = _raw_id
else:
    BOT_IDENTITY = {
        "ENTITY_CODE": "UNKNOWN",
        "JURISDICTION_CODE": "UNKNOWN",
        "BROKER_CODE": "UNKNOWN",
        "BOT_ID": "UNKNOWN",
    }

_UUID_NS = uuid.UUID("76b5c9f8-bf65-4b6a-9d93-2f7b0b5d7a44")  # fixed namespace for deterministic UUIDv5


def _to_utc_iso(dt_str: Optional[str]) -> Optional[str]:
    if not dt_str or not isinstance(dt_str, str):
        return None
    try:
        si = dt_str.replace("Z", "+00:00") if "Z" in dt_str else dt_str
        dt = datetime.fromisoformat(si)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except Exception:
        return None


def _fitid_seed(*parts: Any) -> str:
    buf = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(buf.encode("utf-8")).hexdigest()


def _uuid5(*parts: Any) -> str:
    return str(uuid.uuid5(_UUID_NS, "|".join("" if p is None else str(p) for p in parts)))


def _common_tags() -> Dict[str, str]:
    return {
        "entity_code": BOT_IDENTITY.get("ENTITY_CODE", "UNKNOWN"),
        "jurisdiction_code": BOT_IDENTITY.get("JURISDICTION_CODE", "UNKNOWN"),
        "broker_code": BOT_IDENTITY.get("BROKER_CODE", "UNKNOWN"),
        "bot_id": BOT_IDENTITY.get("BOT_ID", "UNKNOWN"),
    }


def _ofx_trntype_for_trade(action: Optional[str]) -> str:
    a = (action or "").lower()
    return {
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
    }.get(a, "OTHER")


def _ofx_trntype_for_cash(activity_type: Optional[str]) -> str:
    a = (activity_type or "").upper()
    return {
        "DIV": "DIV",
        "INT": "INT",
        "FEE": "FEE",
        "TRANS": "XFER",
        "JOURNAL": "XFER",
        "WITHDRAWAL": "WITHDRAWAL",
        "DEPOSIT": "DEPOSIT",
    }.get(a, "OTHER")


# ---------------------------
# Fallback cores (used only if internal normalizers absent)
# ---------------------------

def _fallback_trade_core(raw: Dict[str, Any]) -> Dict[str, Any]:
    symbol = raw.get("symbol") or raw.get("underlying")
    qty = raw.get("quantity") or raw.get("qty") or raw.get("filled_qty")
    price = raw.get("price") or raw.get("filled_avg_price") or raw.get("fill_price")
    dt = raw.get("datetime_utc") or raw.get("filled_at") or raw.get("transaction_time") or raw.get("submitted_at")
    dt_utc = _to_utc_iso(dt)
    action = (raw.get("action") or raw.get("side") or "").lower() or None
    trntype = _ofx_trntype_for_trade(action)

    trade_id = raw.get("trade_id") or raw.get("order_id") or raw.get("id")
    stable = raw.get("stable_id") or _fitid_seed(BOT_IDENTITY.get("BROKER_CODE"), trade_id, symbol, dt_utc, qty, price)
    fitid = _fitid_seed("TRD", stable)

    total_value = (float(qty or 0) * float(price or 0)) if qty is not None and price is not None else 0.0
    group_seed = raw.get("order_id") or stable or fitid
    return {
        # OFX-aligned
        "TRNTYPE": trntype,
        "DTPOSTED": dt_utc,
        "FITID": fitid,
        "group_id": _uuid5("TRD", group_seed),
        # Canonical economics
        "symbol": symbol,
        "quantity": float(qty or 0),
        "price": float(price or 0),
        "total_value": float(total_value),
        "fee": float(raw.get("fee") or 0),
        "commission": float(raw.get("commission") or 0),
        # Status/meta
        "status": raw.get("status"),
        "description": raw.get("description"),
        "json_metadata": {
            "raw_broker": raw,
            "stable_id": stable,
        },
        # Identity tags
        **_common_tags(),
    }


def _fallback_cash_core(raw: Dict[str, Any]) -> Dict[str, Any]:
    qty = raw.get("quantity") or raw.get("qty")
    price = raw.get("price")
    dt = raw.get("datetime_utc") or raw.get("transaction_time") or raw.get("date")
    dt_utc = _to_utc_iso(dt)
    atype = raw.get("activity_type") or raw.get("action")
    trntype = _ofx_trntype_for_cash(atype)

    aid = raw.get("activity_id") or raw.get("id")
    stable = raw.get("stable_id") or _fitid_seed(BOT_IDENTITY.get("BROKER_CODE"), atype, aid, dt_utc, qty, price)
    fitid = _fitid_seed("ACT", stable)

    amount = (float(qty or 0) * float(price or 0)) if qty is not None and price is not None else float(raw.get("amount") or 0)
    return {
        "TRNTYPE": trntype,
        "DTPOSTED": dt_utc,
        "FITID": fitid,
        "group_id": _uuid5("ACT", atype or "UNKNOWN", aid or stable),
        "symbol": raw.get("symbol"),
        "quantity": float(qty or 0),
        "price": float(price or 0),
        "amount": float(amount),
        "fee": float(raw.get("fee") or 0),
        "commission": float(raw.get("commission") or 0),
        "status": raw.get("status"),
        "description": raw.get("description"),
        "json_metadata": {
            "raw_broker": raw,
            "stable_id": stable,
        },
        **_common_tags(),
    }


def _fallback_position_core(raw: Dict[str, Any]) -> Dict[str, Any]:
    symbol = raw.get("symbol")
    qty = raw.get("qty") or raw.get("quantity")
    avg = raw.get("avg_entry_price") or raw.get("avg_price") or 0
    mv = raw.get("market_value") or 0
    dt = raw.get("datetime_utc") or raw.get("updated_at") or raw.get("timestamp")
    dt_utc = _to_utc_iso(dt)

    pid = raw.get("position_id") or symbol
    stable = raw.get("stable_id") or _fitid_seed(BOT_IDENTITY.get("BROKER_CODE"), "POS", pid, symbol, qty, avg)
    fitid = _fitid_seed("POS", stable)

    return {
        "TRNTYPE": "POS",           # position snapshot entry
        "DTPOSTED": dt_utc,
        "FITID": fitid,
        "group_id": _uuid5("POS", symbol or "UNKNOWN"),
        "symbol": symbol,
        "qty": float(qty or 0),
        "avg_entry_price": float(avg or 0),
        "market_value": float(mv or 0),
        "cost_basis": float(raw.get("cost_basis") or (float(qty or 0) * float(avg or 0))),
        "json_metadata": {
            "raw_broker": raw,
            "stable_id": stable,
        },
        **_common_tags(),
    }


# ---------------------------
# Public API
# ---------------------------

def normalize_trade(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a RAW trade/order record to an OFX-aligned dict:
      required keys: TRNTYPE, DTPOSTED (UTC Z), FITID, group_id
    """
    if not isinstance(raw, dict):
        return {}
    if _HAS_INTERNALS:
        out = _trade_core(raw, BOT_IDENTITY)  # type: ignore
    else:
        out = _fallback_trade_core(raw)
    # Final guards: ensure mandatory keys exist
    out.setdefault("TRNTYPE", "OTHER")
    out["DTPOSTED"] = _to_utc_iso(out.get("DTPOSTED")) or _to_utc_iso(raw.get("datetime_utc")) or out.get("DTPOSTED")
    if not out.get("FITID"):
        out["FITID"] = _fitid_seed("TRD", raw.get("stable_id") or raw.get("trade_id") or raw.get("order_id") or raw)
    out.setdefault("group_id", _uuid5("TRD", out["FITID"]))
    return out


def normalize_cash(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a RAW cash/activity record to an OFX-aligned dict.
    """
    if not isinstance(raw, dict):
        return {}
    if _HAS_INTERNALS:
        out = _cash_core(raw, BOT_IDENTITY)  # type: ignore
    else:
        out = _fallback_cash_core(raw)
    out.setdefault("TRNTYPE", "OTHER")
    out["DTPOSTED"] = _to_utc_iso(out.get("DTPOSTED")) or _to_utc_iso(raw.get("datetime_utc")) or out.get("DTPOSTED")
    if not out.get("FITID"):
        out["FITID"] = _fitid_seed("ACT", raw.get("stable_id") or raw.get("activity_id") or raw)
    out.setdefault("group_id", _uuid5("ACT", out["FITID"]))
    return out


def normalize_position(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a RAW position snapshot to an OFX-aligned dict.
    """
    if not isinstance(raw, dict):
        return {}
    if _HAS_INTERNALS:
        out = _pos_core(raw, BOT_IDENTITY)  # type: ignore
    else:
        out = _fallback_position_core(raw)
    out.setdefault("TRNTYPE", "POS")
    out["DTPOSTED"] = _to_utc_iso(out.get("DTPOSTED")) or _to_utc_iso(raw.get("datetime_utc")) or out.get("DTPOSTED")
    if not out.get("FITID"):
        out["FITID"] = _fitid_seed("POS", raw.get("stable_id") or raw.get("position_id") or raw.get("symbol") or raw)
    out.setdefault("group_id", _uuid5("POS", out["FITID"]))
    return out


__all__ = ["normalize_trade", "normalize_cash", "normalize_position"]
