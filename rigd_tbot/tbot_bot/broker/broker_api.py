# tbot_bot/broker/broker_api.py
# Unified Broker API entry point. Provides both direct adapter loading and simple functional API.
# Calls always use current secrets/config for all supported brokers. All other code must use these functions only.

import hashlib
import importlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tbot_bot.support.decrypt_secrets import (
    decrypt_json,
    load_broker_credential,
)
from tbot_bot.config.env_bot import get_bot_config

ADAPTERS = {
    "ALPACA": "tbot_bot.broker.adapters.alpaca.AlpacaBroker",
    "IBKR": "tbot_bot.broker.adapters.ibkr.IBKRBroker",
    "TRADIER": "tbot_bot.broker.adapters.tradier.TradierBroker",
}

_broker_instance = None
_broker_env = None


def get_broker_env() -> Dict[str, Any]:
    global _broker_env
    if _broker_env is None:
        try:
            cred = decrypt_json("broker_credentials")
            config = get_bot_config()
            _broker_env = {**cred, **config}
        except Exception:
            _broker_env = {}
    return _broker_env


def _active_broker_code() -> str:
    env = get_broker_env()
    return (env.get("BROKER_CODE") or load_broker_credential("BROKER_CODE", "") or "").upper()


def get_active_broker():
    global _broker_instance
    if _broker_instance is not None:
        return _broker_instance

    broker_code = _active_broker_code()
    if broker_code not in ADAPTERS:
        raise RuntimeError(f"[broker_api] Unknown or unset BROKER_CODE: {broker_code}")

    mod_path, cls_name = ADAPTERS[broker_code].rsplit(".", 1)
    module = importlib.import_module(mod_path)
    broker_cls = getattr(module, cls_name)
    _broker_instance = broker_cls(get_broker_env())
    return _broker_instance


def _first_nonempty(d: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v) != "":
            return str(v)
    return None


def _ensure_stable_ids(records: List[Dict[str, Any]], broker_code: str, id_keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """
    Ensure each record has a stable_id suitable as a FITID seed downstream.
    If adapter already provides 'stable_id', it is preserved.
    """
    out = []
    for r in records:
        if not isinstance(r, dict):
            continue
        if "stable_id" in r and r["stable_id"]:
            out.append(r)
            continue
        base = _first_nonempty(r, id_keys) or _first_nonempty(r, ("id", "uuid", "hash"))
        if base is None:
            # last-resort: hash of sorted items to maintain determinism
            try:
                payload = repr(sorted(r.items()))
            except Exception:
                payload = str(r)
            base = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        r = dict(r)
        r["stable_id"] = hashlib.sha1(f"{broker_code}:{base}".encode("utf-8")).hexdigest()
        out.append(r)
    return out


# ---------------------------
# Unified RAW retrieval API
# ---------------------------

def get_trades(start_utc: str, end_utc: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return RAW trade/order-execution-like records from the active broker (no normalization, no DB I/O).
    Adapters must implement get_trades(); legacy names are supported for backward compatibility.
    """
    broker = get_active_broker()
    broker_code = _active_broker_code()
    if hasattr(broker, "get_trades"):
        records = broker.get_trades(start_utc, end_utc)
    elif hasattr(broker, "fetch_all_trades"):
        records = broker.fetch_all_trades(start_utc, end_utc)
    else:
        raise AttributeError(f"{broker.__class__.__name__} missing get_trades/fetch_all_trades")
    # Attach stable IDs without altering other raw fields
    return _ensure_stable_ids(records or [], broker_code, ("trade_id", "execution_id", "order_id", "event_id"))


def get_activities(start_utc: str, end_utc: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return RAW cash/activity records (dividends, fees, transfers, journaling, etc.) from the active broker.
    """
    broker = get_active_broker()
    broker_code = _active_broker_code()
    if hasattr(broker, "get_activities"):
        records = broker.get_activities(start_utc, end_utc)
    elif hasattr(broker, "fetch_cash_activity"):
        records = broker.fetch_cash_activity(start_utc, end_utc)
    else:
        raise AttributeError(f"{broker.__class__.__name__} missing get_activities/fetch_cash_activity")
    return _ensure_stable_ids(records or [], broker_code, ("activity_id", "journal_id", "transaction_id", "event_id"))


def get_positions(as_of_utc: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return RAW open positions snapshot. Adapters may ignore as_of_utc when not supported.
    """
    broker = get_active_broker()
    broker_code = _active_broker_code()
    if hasattr(broker, "get_positions"):
        records = broker.get_positions(as_of_utc=as_of_utc)
    else:
        # legacy name
        records = broker.get_positions()
    return _ensure_stable_ids(records or [], broker_code, ("position_id", "symbol"))


# ---------------------------
# Order and account helpers
# ---------------------------

def place_order(order: Dict[str, Any]):
    broker = get_active_broker()
    if hasattr(broker, "place_order"):
        return broker.place_order(order=order)
    if hasattr(broker, "submit_order"):
        return broker.submit_order(order)
    raise AttributeError(f"{broker.__class__.__name__} has neither place_order nor submit_order method.")


def cancel_order(order_id: str):
    broker = get_active_broker()
    return broker.cancel_order(order_id)


def close_position(order: Dict[str, Any]):
    broker = get_active_broker()
    return broker.close_position(order["symbol"])


def get_account_info() -> Dict[str, Any]:
    broker = get_active_broker()
    return broker.get_account_info()


def is_symbol_tradable(symbol: str) -> bool:
    broker = get_active_broker()
    return broker.is_symbol_tradable(symbol)


def supports_fractional(symbol: str) -> bool:
    broker = get_active_broker()
    return broker.supports_fractional(symbol)


def get_min_order_size(symbol: str) -> Any:
    broker = get_active_broker()
    return broker.get_min_order_size(symbol)


__all__ = [
    "get_active_broker",
    "get_trades",
    "get_activities",
    "get_positions",
    "place_order",
    "cancel_order",
    "close_position",
    "get_account_info",
    "is_symbol_tradable",
    "supports_fractional",
    "get_min_order_size",
]
