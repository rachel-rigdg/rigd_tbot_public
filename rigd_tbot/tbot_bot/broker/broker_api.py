# tbot_bot/broker/broker_api.py
# Unified Broker API entry point. Provides both direct adapter loading and simple functional API.
# Calls always use current secrets/config for all supported brokers. All other code must use these functions only.

import importlib
from typing import Any, Dict, List

from tbot_bot.support.decrypt_secrets import (
    decrypt_json,
    load_broker_credential,
)
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade

# Prefer the central compliance filter; fall back to a local-lite filter if unavailable.
try:
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (
        compliance_filter_entries as _compliance_filter_entries,
    )
    _HAS_COMPLIANCE = True
except Exception:
    _HAS_COMPLIANCE = False
    _PRIMARY_FIELDS = ("symbol", "datetime_utc", "action", "price", "quantity", "total_value")
    _ALLOWED_ACTIONS = {
        "long", "short", "put", "call", "assignment", "exercise", "expire", "reorg", "inverse", "other",
        # accepted system/ops actions (harmless if unused)
        "reserve_tax", "reserve_payroll", "float_allocation", "rebalance_buy", "rebalance_sell",
    }

    def _is_blank_primary(entry: Dict[str, Any]) -> bool:
        return all(entry.get(f) is None or str(entry.get(f)).strip() == "" for f in _PRIMARY_FIELDS)

    def _lite_filter(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            if _is_blank_primary(e):
                continue
            action = e.get("action")
            if action not in _ALLOWED_ACTIONS:
                continue
            if e.get("skip_insert"):
                continue
            jm = e.get("json_metadata")
            if isinstance(jm, dict) and isinstance(jm.get("raw_broker"), dict):
                # Drop obvious status-only markers that may slip through normalization
                raw = jm["raw_broker"]
                hint = str(
                    raw.get("activity_type") or raw.get("type") or raw.get("order_status") or ""
                ).upper()
                if hint in {"NEW", "PENDING_NEW", "ACCEPTED", "CANCELED", "CANCELLED",
                            "REPLACED", "REJECTED", "EXPIRED", "PARTIAL_FILL", "PARTIALLY_FILLED",
                            "PENDING_CANCEL", "FILL"}:
                    # Only admit them if they have clear economics (nonzero total_value or fees)
                    tv = float(e.get("total_value") or 0)  # safe cast
                    fees = float(e.get("fee") or 0) + float(e.get("commission") or 0)
                    if tv == 0 and fees == 0:
                        continue
            filtered.append(e)
        return filtered


ADAPTERS = {
    "ALPACA": "tbot_bot.broker.adapters.alpaca.AlpacaBroker",
    "IBKR": "tbot_bot.broker.adapters.ibkr.IBKRBroker",
    "TRADIER": "tbot_bot.broker.adapters.tradier.TradierBroker",
}

_broker_instance = None
_broker_env = None


def get_broker_env():
    global _broker_env
    if _broker_env is None:
        try:
            # Strongest version: combine all config + secrets for max compatibility
            cred = decrypt_json("broker_credentials")
            config = get_bot_config()
            _broker_env = {**cred, **config}
        except Exception:
            _broker_env = {}
    return _broker_env


def get_active_broker():
    global _broker_instance
    if _broker_instance is not None:
        return _broker_instance

    env = get_broker_env()
    broker_code = (env.get("BROKER_CODE") or load_broker_credential("BROKER_CODE", "") or "").upper()
    if broker_code not in ADAPTERS:
        raise RuntimeError(f"[broker_api] Unknown or unset BROKER_CODE: {broker_code}")

    mod_path, cls_name = ADAPTERS[broker_code].rsplit(".", 1)
    module = importlib.import_module(mod_path)
    broker_cls = getattr(module, cls_name)
    _broker_instance = broker_cls(env)

    # --- HARD REDIRECT: force any broker.get_price(...) to use Screeners creds (e.g., FINNHUB)
    try:
        def _screeners_get_price(self, symbol: str) -> float:
            from tbot_bot.screeners.screener_utils import get_realtime_price
            return get_realtime_price(symbol)
        # bind method to instance regardless of adapter implementation
        _broker_instance.get_price = _screeners_get_price.__get__(_broker_instance, _broker_instance.__class__)
    except Exception:
        # best-effort; we still provide a module-level fallback get_price()
        pass

    return _broker_instance


def _normalize_and_filter(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize broker records and filter out blanks/unmapped/status-only noise."""
    normalized = [normalize_trade(r) for r in records if isinstance(r, dict)]
    if _HAS_COMPLIANCE:
        return _compliance_filter_entries(normalized)
    # Fallback path if compliance module not importable
    return _lite_filter(normalized)


def place_order(order):
    broker = get_active_broker()
    if hasattr(broker, "place_order"):
        return broker.place_order(order=order)
    elif hasattr(broker, "submit_order"):
        return broker.submit_order(order)
    else:
        raise AttributeError(f"{broker.__class__.__name__} has neither place_order nor submit_order method.")


def cancel_order(order_id):
    broker = get_active_broker()
    return broker.cancel_order(order_id)


def close_position(order):
    broker = get_active_broker()
    return broker.close_position(order["symbol"])


def get_account_info():
    broker = get_active_broker()
    return broker.get_account_info()


def get_positions():
    broker = get_active_broker()
    return broker.get_positions()


def is_symbol_tradable(symbol):
    broker = get_active_broker()
    return broker.is_symbol_tradable(symbol)


def supports_fractional(symbol):
    broker = get_active_broker()
    return broker.supports_fractional(symbol)


def get_min_order_size(symbol):
    broker = get_active_broker()
    return broker.get_min_order_size(symbol)


def fetch_all_trades(start_date, end_date=None):
    broker = get_active_broker()
    trades = broker.fetch_all_trades(start_date, end_date)
    return _normalize_and_filter(trades)


def fetch_cash_activity(start_date, end_date=None):
    broker = get_active_broker()
    acts = broker.fetch_cash_activity(start_date, end_date)
    return _normalize_and_filter(acts)


# --- MODULE-LEVEL PRICE HELPER: keep callers off broker adapters entirely
def get_price(symbol: str) -> float:
    """Single source of truth for market prices via Screeners (e.g., FINNHUB)."""
    from tbot_bot.screeners.screener_utils import get_realtime_price
    return get_realtime_price(symbol)


# --- NEW: trailing-stop & reference-price helpers (adapter passthroughs) ---

def supports_trailing_stops() -> bool:
    """Return True if the active adapter can place native trailing stops."""
    broker = get_active_broker()
    fn = getattr(broker, "supports_trailing_stops", None)
    return bool(fn() if callable(fn) else False)


def place_trailing_stop(payload: Dict[str, Any]):
    """
    Forward a trailing stop request to the active adapter.

    Expected payload fields (orders_bot supplies these):
      symbol, qty, side, trail_percent (2.0), trail_pct_fraction (0.02), strategy, time
    """
    broker = get_active_broker()
    fn = getattr(broker, "place_trailing_stop", None)
    if not callable(fn):
        return {"error": "unsupported"}
    return fn(payload)


def get_last_price(symbol: str) -> float | None:
    """
    Lightweight reference price for qty estimation when FRACTIONAL is false.
    Defaults to screener-backed realtime price.
    Adapters may override with a venue-native quote if desired.
    """
    broker = get_active_broker()
    fn = getattr(broker, "get_last_price", None)
    if callable(fn):
        try:
            p = fn(symbol)
            return float(p) if p is not None else None
        except Exception:
            pass
    try:
        return float(get_price(symbol))
    except Exception:
        return None


__all__ = [
    "get_active_broker",
    "place_order",
    "cancel_order",
    "close_position",
    "get_account_info",
    "get_positions",
    "is_symbol_tradable",
    "supports_fractional",
    "get_min_order_size",
    "fetch_all_trades",
    "fetch_cash_activity",
    "get_price",
    # new exports
    "supports_trailing_stops",
    "place_trailing_stop",
    "get_last_price",
]
