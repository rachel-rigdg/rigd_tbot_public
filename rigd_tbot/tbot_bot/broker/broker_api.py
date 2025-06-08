# tbot_bot/broker/broker_api.py
# Unified broker interface and trade dispatch router (single-broker mode)

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.broker.brokers.broker_alpaca import AlpacaBroker
from tbot_bot.broker.brokers.broker_ibkr import IBKRBroker
from tbot_bot.trading.logs_bot import log_event

# Always load config at runtime for fresh settings
def get_active_broker():
    """
    Returns the initialized broker object based on BROKER_NAME in env_bot.
    """
    config = get_bot_config()
    broker_name = config.get("BROKER_NAME", "").lower()
    if broker_name == "alpaca":
        return AlpacaBroker(config)
    elif broker_name == "ibkr":
        return IBKRBroker(config)
    else:
        raise RuntimeError(f"[broker_api] Unsupported or missing BROKER_NAME: {broker_name}")

def place_order(order):
    """
    Submit an order to the active broker.
    Args:
        order (dict): {
            'symbol': str,
            'side': 'buy' or 'sell',
            'qty': float,
            'order_type': 'market' or 'limit',
            'strategy': str
        }
    Returns:
        dict: Order response or error details
    """
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
