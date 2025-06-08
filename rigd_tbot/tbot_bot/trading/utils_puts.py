# tbot_bot/trading/utils_puts.py
# Returns put option contract specs for any supported broker

from tbot_bot.support.utils_log import log_debug

def get_put_option(symbol, expiry=None, strike=None, broker="generic"):
    """
    Returns put option contract spec for the given symbol, formatted for the broker.
    Args:
        symbol (str): underlying ticker from screener/strategy
        expiry (str): option expiry in YYYYMMDD (optional, defaults to 'NEAREST')
        strike (float): strike price (optional, defaults to 'ATM')
        broker (str): broker name ("ibkr", "alpaca", "tradier", etc.)
    Returns:
        dict: contract specification, broker-formatted
    """
    if not symbol:
        log_debug("Empty symbol provided to get_put_option", module="utils_puts")
        return None

    symbol = symbol.upper()
    expiry = expiry or "NEAREST"
    strike = strike or "ATM"

    if broker.lower() == "ibkr":
        contract = {
            "symbol": symbol,
            "secType": "OPT",
            "right": "P",
            "expiry": expiry,
            "strike": strike,
            "currency": "USD",
            "exchange": "SMART"
        }
    elif broker.lower() == "alpaca":
        contract = {
            "symbol": symbol,
            "type": "option",
            "side": "put",
            "expiry": expiry,
            "strike": strike,
            "currency": "USD",
            "venue": "OPRA"
        }
    else:
        # Generic/expandable spec; broker adapters can map fields as needed
        contract = {
            "symbol": symbol,
            "option_type": "put",
            "expiry": expiry,
            "strike": strike,
            "currency": "USD"
        }

    return contract
