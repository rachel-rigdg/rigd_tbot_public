# tbot_bot/enhancements/vix_gatekeeper.py
# Blocks close strategy if VIX is under threshold
# -------------------------------------------------------

import requests
import time
from tbot_bot.support.utils_log import log_debug, log_error  # UPDATED
from tbot_bot.config.env_bot import get_bot_config

# Load config
config = get_bot_config()
FINNHUB_API_KEY = config.get("FINNHUB_API_KEY", "")

# Cache to avoid excessive requests
_vix_cache = {"value": None, "timestamp": 0}
CACHE_DURATION = 60  # seconds

def get_vix_value():
    """
    Fetches the current VIX index value from Finnhub.
    Caches result for CACHE_DURATION to reduce API calls.
    """
    global _vix_cache
    current_time = time.time()

    if _vix_cache["value"] is not None and (current_time - _vix_cache["timestamp"] < CACHE_DURATION):
        return _vix_cache["value"]

    if not FINNHUB_API_KEY:
        log_error("[vix_gatekeeper] FINNHUB_API_KEY is missing from config.")
        return None

    try:
        response = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol=^VIX&token={FINNHUB_API_KEY}"
        )
        response.raise_for_status()
        data = response.json()
        vix = float(data.get("c", 0))
        _vix_cache = {"value": vix, "timestamp": current_time}
        log_debug(f"[vix_gatekeeper] Current VIX: {vix}")
        return vix
    except Exception as e:
        log_error(f"[vix_gatekeeper] Failed to fetch VIX: {e}")
        return None

def is_vix_above_threshold(threshold: float) -> bool:
    """
    Returns True if VIX is greater than or equal to threshold.
    Used by strategy_close to block trades in low-volatility environments.
    """
    vix = get_vix_value()
    if vix is None:
        log_debug("[vix_gatekeeper] Could not retrieve VIX, defaulting to allow trade.")
        return True  # Fail open
    return vix >= threshold
