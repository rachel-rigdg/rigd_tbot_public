# tbot_bot/broker/broker_api.py
# Unified broker interface and trade dispatch router (single-broker mode only, per spec).

from tbot_bot.support.decrypt_secrets import load_broker_credential
from tbot_bot.support.utils_log import log_event
from tbot_bot.config.env_bot import get_bot_config

def get_active_broker():
    """
    Returns the initialized broker object based on BROKER_CODE (BROKER_NAME) from broker_credentials.json.enc.
    Only ONE broker module is loaded per instance.
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
        from tbot_bot.broker.brokers.alpaca import AlpacaBroker
        return AlpacaBroker(broker_credentials)
    elif broker_code == "ibkr":
        from tbot_bot.broker.brokers.ibkr import IBKRBroker
        return IBKRBroker(broker_credentials)
    elif broker_code == "tradier":
        from tbot_bot.broker.brokers.tradier import TradierBroker
        return TradierBroker(broker_credentials)
    else:
        raise RuntimeError(f"[broker_api] Unsupported or missing BROKER_CODE: {broker_code}")

def place_order(order):
    """Submits an order via the active broker."""
    try:
        broker = get_active_broker()
        return broker.submit_order(order)
    except Exception as e:
        log_event("broker_api", f"Order failed: {e}", level="error")
        return {"error": str(e)}

def cancel_order(order_id):
    """Cancels an order by ID via the active broker."""
    try:
        broker = get_active_broker()
        return broker.cancel_order(order_id)
    except Exception as e:
        log_event("broker_api", f"Cancel error: {e}", level="error")
        return {"error": str(e)}

def close_position(order):
    """Closes a position for the given symbol via the active broker."""
    try:
        broker = get_active_broker()
        return broker.close_position(order["symbol"])
    except Exception as e:
        log_event("broker_api", f"Close position error: {e}", level="error")
        return {"error": str(e)}

def get_account_info():
    """Returns account info for the active broker."""
    try:
        broker = get_active_broker()
        return broker.get_account_info()
    except Exception as e:
        log_event("broker_api", f"Account info error: {e}", level="error")
        return {"error": str(e)}

def get_positions():
    """Returns all open positions for the active broker."""
    try:
        broker = get_active_broker()
        return broker.get_positions()
    except Exception as e:
        log_event("broker_api", f"Get positions error: {e}", level="error")
        return {"error": str(e)}

def is_symbol_tradable(symbol):
    """Returns True if symbol is tradable on the active broker."""
    try:
        broker = get_active_broker()
        return broker.is_symbol_tradable(symbol)
    except Exception as e:
        log_event("broker_api", f"is_symbol_tradable error: {e}", level="error")
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
        log_event("broker_api", f"supports_fractional error: {e}", level="error")
        return False

def get_min_order_size(symbol):
    """
    Returns the minimum order size for the symbol for the current broker.
    """
    try:
        broker = get_active_broker()
        return broker.get_min_order_size(symbol)
    except Exception as e:
        log_event("broker_api", f"get_min_order_size error: {e}", level="error")
        return 1.0

# ==================== SPEC ENFORCEMENT: BROKER LEDGER SYNC INTERFACE ====================

def fetch_all_trades(start_date, end_date=None):
    """
    Returns all filled trades (OFX/ledger-normalized dicts) for the active broker.
    Calls broker.fetch_all_trades(), logs sync event.
    """
    try:
        broker = get_active_broker()
        trades = broker.fetch_all_trades(start_date, end_date)
        log_event("broker_api", f"fetch_all_trades: {len(trades)} trades, start={start_date}, end={end_date}", level="info")
        return trades
    except Exception as e:
        log_event("broker_api", f"fetch_all_trades error: {e}", level="error")
        return []

def fetch_cash_activity(start_date, end_date=None):
    """
    Returns all cash/dividend/fee activity (OFX/ledger-normalized dicts) for the active broker.
    Calls broker.fetch_cash_activity(), logs sync event.
    """
    try:
        broker = get_active_broker()
        activity = broker.fetch_cash_activity(start_date, end_date)
        log_event("broker_api", f"fetch_cash_activity: {len(activity)} entries, start={start_date}, end={end_date}", level="info")
        return activity
    except Exception as e:
        log_event("broker_api", f"fetch_cash_activity error: {e}", level="error")
        return []

# Only one broker instance is ever active per bot process.
# Support for multi-broker will require dispatcher changes at orchestration level.
