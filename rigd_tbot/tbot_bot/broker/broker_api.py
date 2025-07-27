# tbot_bot/broker/broker_api.py
# Unified Broker API entry point. Provides both direct adapter loading and simple functional API.
# Calls always use current secrets/config for all supported brokers. All other code must use these functions only.

import importlib
from tbot_bot.support.decrypt_secrets import (
    decrypt_json,
    load_broker_credential
)
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade

ADAPTERS = {
    "ALPACA": "tbot_bot.broker.adapters.alpaca.AlpacaBroker",
    "IBKR": "tbot_bot.broker.adapters.ibkr.IBKRBroker",
    "TRADIER": "tbot_bot.broker.adapters.tradier.TradierBroker"
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
    return _broker_instance

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
    # ENFORCE NORMALIZATION ON ALL OUTPUTS
    return [normalize_trade(t) for t in trades if isinstance(t, dict)]

def fetch_cash_activity(start_date, end_date=None):
    broker = get_active_broker()
    acts = broker.fetch_cash_activity(start_date, end_date)
    # ENFORCE NORMALIZATION ON ALL OUTPUTS
    return [normalize_trade(c) for c in acts if isinstance(c, dict)]

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
    "fetch_cash_activity"
]
