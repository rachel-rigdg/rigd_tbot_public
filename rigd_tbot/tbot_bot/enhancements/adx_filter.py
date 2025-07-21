# tbot_bot/enhancements/adx_filter.py
# Blocks mid-session trades during trending ADX conditions
# ------------------------------------------------------
# Blocks VWAP mean reversion trades when ADX is high (strong trend)
# Used by: strategy_mid.py, risk_module.py

from typing import Optional, Tuple
import requests
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_debug

config = get_bot_config()
SCREENER_API_KEY = config.get("SCREENER_API_KEY", "") or config.get("FINNHUB_API_KEY", "")
SCREENER_URL = config.get("SCREENER_URL", "https://finnhub.io/api/v1/")
ADX_FILTER_THRESHOLD = 25  # Block trades if ADX > this

def get_adx(symbol: str, resolution: str = "5", length: int = 14) -> Optional[float]:
    """
    Fetches ADX value for the symbol from Finnhub.
    Returns latest ADX as float, or None if unavailable/error.
    Never raises.
    """
    try:
        url = (
            f"{SCREENER_URL.rstrip('/')}/indicator"
            f"?symbol={symbol}&resolution={resolution}&indicator=adx"
            f"&timeperiod={length}&token={SCREENER_API_KEY}"
        )
        resp = requests.get(url, timeout=5)
        data = resp.json()
        adx_values = data.get("adx", {}).get("value", [])
        if adx_values:
            latest_adx = adx_values[-1]
            log_debug(f"[adx_filter] ADX for {symbol}: {latest_adx}")
            return float(latest_adx)
    except Exception as e:
        log_debug(f"[adx_filter] Error fetching ADX for {symbol}: {e}")
    return None

def is_trade_blocked_by_adx(symbol: str) -> Tuple[bool, Optional[str]]:
    """
    Returns (True, reason) if trade should be blocked by ADX.
    Returns (False, None) if trade is allowed or ADX is unavailable.
    NEVER raises.
    """
    adx = get_adx(symbol)
    if adx is None:
        return (False, None)  # Cannot block if ADX unavailable
    if adx >= ADX_FILTER_THRESHOLD:
        return (True, f"ADX too high ({adx:.2f}), strong trend")
    return (False, None)
