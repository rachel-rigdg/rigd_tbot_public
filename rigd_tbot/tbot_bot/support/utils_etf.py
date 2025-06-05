# tbot_bot/support/utils_etf.py
# Resolves ETF and inverse ETF tickers for supported symbols

from tbot_bot.support.utils_log import log_debug

INVERSE_ETF_MAP = {
    "SPY": "SH",
    "QQQ": "PSQ",
    "IWM": "RWM",
    "DIA": "DOG",
    "XLK": "REW",
    "XLF": "FAZ"
}

def get_inverse_etf(symbol):
    """
    Maps a long-side symbol to its inverse ETF equivalent.
    Returns None if no mapping exists.
    """
    inverse_symbol = INVERSE_ETF_MAP.get(symbol.upper())
    if not inverse_symbol:
        log_debug(f"No inverse ETF mapping found for symbol: {symbol}", module="inverse_mapper")
    return inverse_symbol
