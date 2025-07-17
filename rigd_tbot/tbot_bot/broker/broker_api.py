# tbot_bot/broker/broker_api.py
# Unified broker interface and trade dispatch router (single-broker mode)

from tbot_bot.support.decrypt_secrets import load_broker_credential
from tbot_bot.broker.brokers.broker_alpaca import AlpacaBroker
from tbot_bot.broker.brokers.ibkr import IBKRBroker
from tbot_bot.broker.broker_tradier import TradierBroker
from tbot_bot.trading.logs_bot import log_event
from tbot_bot.config.env_bot import get_bot_config

def get_active_broker():
    """
    Returns the initialized broker object based on BROKER_CODE (BROKER_NAME) from broker_credentials.json.enc.
    """
    broker_code = load_broker_credential("BROKER_CODE", "").lower()
    config = get_bot_config()
    broker_credentials = {
        "BROKER_CODE": broker_code,
        "BROKER_HOST": load_broker_credential("BROKER_HOST", ""),
        "BROKER_USERNAME": load_broker_credential("BROKER_USERNAME", ""),
        "BROKER_PASSWORD": load_broker_credential("BROKER_PASSWORD", ""),
        "BROKER_ACCOUNT_NUMBER": load_broker_credential("BROKER_ACCOUNT_NUMBER", ""),
        "BROKER_API_KEY": load_broker_credential("BROKER_API_KEY", ""),
        "BROKER_SECRET_KEY": load_broker_credential("BROKER_SECRET_KEY", ""),
        "BROKER_URL": load_broker_credential("BROKER_URL", ""),
        "BROKER_TOKEN": load_broker_credential("BROKER_TOKEN", ""),
        **config
    }
    if broker_code == "alpaca":
        return AlpacaBroker(broker_credentials)
    elif broker_code == "ibkr":
        return IBKRBroker(broker_credentials)
    elif broker_code == "tradier":
        return TradierBroker(broker_credentials)
    else:
        raise RuntimeError(f"[broker_api] Unsupported or missing BROKER_CODE: {broker_code}")

def place_order(order):
    try:
        broker = get_active_broker()
        return broker.submit_order(order)
    except Exception as e:
        log_event("broker_api", f"Order failed: {e}")
        return {"error": str(e)}

def cancel_order(order_id):
    try:
        broker = get_active_broker()
        return broker.cancel_order(order_id)
    except Exception as e:
        log_event("broker_api", f"Cancel error: {e}")
        return {"error": str(e)}

def close_position(order):
    try:
        broker = get_active_broker()
        return broker.close_position(order["symbol"])
    except Exception as e:
        log_event("broker_api", f"Close position error: {e}")
        return {"error": str(e)}

def get_account_info():
    try:
        broker = get_active_broker()
        return broker.get_account_info()
    except Exception as e:
        log_event("broker_api", f"Account info error: {e}")
        return {"error": str(e)}

def get_positions():
    try:
        broker = get_active_broker()
        return broker.get_positions()
    except Exception as e:
        log_event("broker_api", f"Get positions error: {e}")
        return {"error": str(e)}

def is_symbol_tradable(symbol):
    try:
        broker = get_active_broker()
        return broker.is_symbol_tradable(symbol)
    except Exception as e:
        log_event("broker_api", f"is_symbol_tradable error: {e}")
        return False

# ========== SPEC ENFORCEMENT BELOW ==========

def supports_fractional(symbol):
    """
    Returns True if the current broker supports fractional for symbol.
    """
    try:
        broker = get_active_broker()
        return broker.supports_fractional(symbol)
    except Exception as e:
        log_event("broker_api", f"supports_fractional error: {e}")
        return False

def get_min_order_size(symbol):
    """
    Returns the minimum order size for the symbol for the current broker.
    """
    try:
        broker = get_active_broker()
        return broker.get_min_order_size(symbol)
    except Exception as e:
        log_event("broker_api", f"get_min_order_size error: {e}")
        return 1.0
