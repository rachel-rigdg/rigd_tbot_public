# tbot_bot/trading/instruments.py
# Maps symbols to the appropriate bearish trading instrument (inverse ETF, synthetic, or put option)
# Used by strategy modules to resolve the correct instrument for short/hedge logic

from tbot_bot.support.utils_log import log_event
from tbot_bot.trading.utils_etf import get_inverse_etf
from tbot_bot.trading.utils_puts import get_put_option
from tbot_bot.trading.utils_shorts import get_synthetic_short

def resolve_bearish_instrument(symbol, short_type):
    """
    Resolves the correct instrument to use for bearish exposure.
    :param symbol: str, underlying ticker
    :param short_type: str, "InverseETF", "Short", "Put", or "Synthetic"
    :return: str, instrument ticker to trade (or None if not supported)
    """
    if short_type == "InverseETF":
        etf = get_inverse_etf(symbol)
        if etf:
            return etf
        else:
            log_event("instruments", f"No inverse ETF mapping for {symbol}")
            return None
    elif short_type == "Short":
        return symbol
    elif short_type == "Put":
        put = get_put_option(symbol)
        if put:
            return put
        else:
            log_event("instruments", f"Put option not available for {symbol}")
            return None
    elif short_type == "Synthetic":
        synthetic = get_synthetic_short(symbol)
        if synthetic:
            return synthetic
        else:
            log_event("instruments", f"Synthetic short not available for {symbol}")
            return None
    else:
        log_event("instruments", f"Unsupported short_type: {short_type}")
        return None
