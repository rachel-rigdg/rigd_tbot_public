# tbot_bot/enhancements/adx_filter.py
# Blocks mid-session trades during trending ADX conditions
# ------------------------------------------------------
# Blocks VWAP mean reversion trades when ADX is high (strong trend)
# Used by: strategy_mid.py

from typing import Optional
import requests
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_debug  # UPDATED

config = get_bot_config()
SCREENER_API_KEY = config.get("SCREENER_API_KEY", "") or config.get("FINNHUB_API_KEY", "")
SCREENER_URL = config.get("SCREENER_URL", "https://finnhub.io/api/v1/")
ADX_FILTER_THRESHOLD = 25  # Block trades if ADX > this

def get_adx(symbol: str, resolution: str = "5", length: int = 14) -> Optional[float]:
    """
    Fetches ADX value for the symbol from Finnhub.
    Returns None if unavailable.
    """
    try:
        url = (
            f"{SCREENER_URL.rstrip('/')}/indicator"
            f"?symbol={symbol}&resolution={resolution}&indicator=adx"
            f"&timeperiod={length}&token={SCREENER_API_KEY}"
        )
        resp = requests.get(url)
        data = resp.json()

        if "adx" in data and "value" in data["adx"]:
            adx_values = data["adx"]["value"]
            if adx_values:
                latest_adx = adx_values[-1]
                log_debug(f"[adx_filter] ADX for {symbol}: {latest_adx}")
                return latest_adx
    except Exception as e:
        log_debug(f"[adx_filter] Error fetching ADX for {symbol}: {e}")

    return None

def adx_filter(symbol: str) -> bool:
    """
    Returns True if trade is allowed, False if ADX indicates strong trend.
    """
    adx = get_adx(symbol)
    if adx is None:
        return True  # Fallback: allow trade if ADX is unavailable
    return adx < ADX_FILTER_THRESHOLD
