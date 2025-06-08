# tbot_bot/trading/orders_bot.py
# Submit, modify, or cancel broker orders

"""
Creates and sends orders through the broker API interface.
Handles both market and stop-loss logic based on config.
"""

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.broker.broker_api import place_order, close_position
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.decrypt_secrets import decrypt_json

config = get_bot_config()
MAX_RISK_PER_TRADE = config.get("MAX_RISK_PER_TRADE", 0.025)
FRACTIONAL = config.get("FRACTIONAL", True)
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))

# Retrieve BROKER_CODE (BROKER_NAME) from broker_credentials.json.enc (not .env_bot)
broker_creds = decrypt_json("broker_credentials")
BROKER_NAME = broker_creds.get("BROKER_CODE", "ALPACA").lower()

def create_order(symbol, side, capital, price, stop_loss_pct=0.02, strategy=None):
    """
    Create and submit a new order.
    :param symbol: str, stock ticker
    :param side: str, 'buy' or 'sell'
    :param capital: float, allocated capital
    :param price: float, current market price
    :param stop_loss_pct: float, trailing stop loss (as fraction)
    :param strategy: str, strategy name
    :return: dict with order metadata or None if failed
    """
    if price < MIN_PRICE or price > MAX_PRICE:
        log_event("orders_bot", f"Price out of bounds for {symbol}: {price}")
        return None

    if FRACTIONAL:
        qty = capital / price
    else:
        qty = int(capital / price)
        if qty < 1:
            log_event("orders_bot", f"Insufficient capital for full share of {symbol} at {price}")
            return None

    if qty <= 0:
        log_event("orders_bot", f"Invalid quantity computed for {symbol} at {price}")
        return None

    order = {
        "symbol": symbol,
        "qty": round(qty, 4),
        "side": side,
        "type": "market",
        "strategy": strategy,
        "price": price,
        "total_value": round(qty * price, 2),
        "timestamp": utc_now().isoformat(),
        "trailing_stop_pct": stop_loss_pct,
        "broker": BROKER_NAME,
        "account": "live"
    }

    response = place_order(order)
    if isinstance(response, dict) and response.get("error"):
        log_event("orders_bot", f"Order failed for {symbol}: {response}")
        return None

    log_event("orders_bot", f"Order placed: {order}")
    return order

def exit_order(symbol, side, qty, strategy=None):
    """
    Exit an open position (market close).
    :param symbol: str
    :param side: str, 'sell' or 'buy'
    :param qty: float or int
    :param strategy: optional label
    :return: dict with order metadata or None
    """
    order = {
        "symbol": symbol,
        "qty": round(qty, 4),
        "side": side,
        "type": "market",
        "strategy": strategy,
        "timestamp": utc_now().isoformat(),
        "broker": BROKER_NAME,
        "account": "live"
    }

    response = close_position(order)
    if isinstance(response, dict) and response.get("error"):
        log_event("orders_bot", f"Exit order failed for {symbol}: {response}")
        return None

    log_event("orders_bot", f"Exit order placed: {order}")
    return order
