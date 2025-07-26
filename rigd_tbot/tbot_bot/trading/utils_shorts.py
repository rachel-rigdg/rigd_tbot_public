# tbot_bot/trading/utils_shorts.py
# Provides broker-agnostic helpers for executing short trades, including real shorts, synthetic shorts, and alternatives

from tbot_bot.support.utils_log import log_debug

def get_short_instrument(symbol, broker, short_type="Short"):
    """
    Resolves the correct shorting method/instrument for the given broker.
    Args:
        symbol (str): Underlying ticker selected by the screener/strategy.
        broker (str): Broker identifier (e.g., 'alpaca', 'ibkr', 'tradier').
        short_type (str): Type of shorting ('Short', 'Synthetic', etc.)
    Returns:
        dict: Instrument or method spec for broker API; None if unsupported.
    """
    broker = broker.lower()
    short_type = short_type.lower()

    # Native broker-supported short sale
    if short_type == "short":
        if broker in ("alpaca", "ibkr", "tradier"):
            # Direct short is supported if margin account and shares available to borrow
            return {
                "instrument_type": "equity",
                "method": "short",
                "symbol": symbol.upper()
            }
        else:
            log_debug(f"Broker {broker} does not support direct short selling", module="utils_shorts")
            return None

    # Synthetic shorts (options-based, broker-agnostic but not all brokers support multi-leg)
    elif short_type == "synthetic":
        # Synthetic short = long put + short call (same strike, same expiry)
        # Option chain must be available via broker API; this returns a spec for further resolution
        return {
            "instrument_type": "synthetic_short",
            "legs": [
                {
                    "symbol": symbol.upper(),
                    "secType": "OPT",
                    "right": "P",
                    "expiry": "NEAREST",
                    "strike": "ATM",
                    "action": "BUY"
                },
                {
                    "symbol": symbol.upper(),
                    "secType": "OPT",
                    "right": "C",
                    "expiry": "NEAREST",
                    "strike": "ATM",
                    "action": "SELL"
                }
            ]
        }

    # Broker/strategy can add more types as needed (e.g., inverse ETFs, covered shorts)
    else:
        log_debug(f"Unsupported short_type: {short_type}", module="utils_shorts")
        return None

def get_synthetic_short(symbol, broker=None):
    """
    Stub for test/backtest and import compatibility.
    Returns a synthetic short spec (see get_short_instrument).
    """
    return get_short_instrument(symbol, broker or "ibkr", short_type="synthetic")
