# tbot_bot/broker/broker_api.py
# Unified broker interface and trade dispatch router (single-broker mode)

from tbot_bot.support.decrypt_secrets import load_broker_credential
from tbot_bot.broker.brokers.broker_alpaca import AlpacaBroker
from tbot_bot.broker.brokers.broker_ibkr import IBKRBroker
from tbot_bot.trading.logs_bot import log_event
from tbot_bot.config.env_bot import get_bot_config

def get_active_broker():
    """
    Returns the initialized broker object based on BROKER_CODE (BROKER_NAME) from broker_credentials.json.enc.
    """
    broker_code = load_broker_credential("BROKER_CODE", "").lower()
    config = get_bot_config()
    # Provide broker credentials from decrypted secrets
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
        **config  # merge in runtime config for risk/strategy settings, etc.
    }

    if broker_code == "alpaca":
        return AlpacaBroker(broker_credentials)
    elif broker_code == "ibkr":
        return IBKRBroker(broker_credentials)
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
