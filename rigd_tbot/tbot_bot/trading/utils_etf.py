# tbot_bot/trading/utils_etf.py
# Resolves ETF and inverse ETF tickers for supported symbols (top 20+ ETFs, as per project specifications)

from tbot_bot.support.utils_log import log_debug

INVERSE_ETF_MAP = {
    # Broad Index ETFs
    "SPY":  "SH",       # S&P 500
    "VOO":  "SH",       # S&P 500 (Vanguard)
    "IVV":  "SH",       # S&P 500 (iShares)
    "QQQ":  "PSQ",      # Nasdaq 100
    "VTI":  "VXX",      # Total Market (best effort, VXX = volatility, no true 1x inverse)
    "IWM":  "RWM",      # Russell 2000
    "DIA":  "DOG",      # Dow 30

    # Leveraged Index Inverse
    "SPXL": "SPXS",     # S&P 500 3x Bull → 3x Bear
    "TQQQ": "SQQQ",     # Nasdaq 100 3x Bull → 3x Bear
    "UPRO": "SPXU",     # S&P 500 3x Bull → 3x Bear

    # Sector ETFs (Top SPDRs)
    "XLF":  "FAZ",      # Financials
    "XLK":  "REW",      # Technology
    "XLV":  "RXD",      # Health Care
    "XLY":  "SCC",      # Consumer Discretionary
    "XLI":  "SIJ",      # Industrials
    "XLE":  "ERY",      # Energy
    "XLB":  "SMN",      # Materials
    "XLRE": "DRV",      # Real Estate
    "XLU":  "SDP",      # Utilities
    "XLC":  "YANG",     # Communication (best effort, YANG = China comm 3x Bear)
    
    # Additional Major Inverse ETFs (non-SPDR)
    "VXX":  "SVXY",     # Volatility long → inverse vol
    "EFA":  "EFZ",      # MSCI EAFE
    "EEM":  "EEV",      # Emerging Markets

    # Commodities/Other
    "GLD":  "DGZ",      # Gold → inverse gold
    "SLV":  "ZSL",      # Silver → 2x inverse silver

    # Add more as needed
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
