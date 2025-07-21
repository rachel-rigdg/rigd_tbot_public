# tbot_bot/enhancements/vix_gatekeeper.py
# Blocks close strategy if VIX is under threshold
# -------------------------------------------------------

import requests
import time
from tbot_bot.support.utils_log import log_debug, log_error  # UPDATED
from tbot_bot.support.secrets_manager import load_screener_credentials

# Cache to avoid excessive requests
_vix_cache = {"value": None, "timestamp": 0}
CACHE_DURATION = 60  # seconds

def get_finnhub_api_params():
    """
    Loads the first enabled Finnhub screener API key and URL from encrypted credentials.
    """
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"TRADING_ENABLED_{k.split('_')[-1]}", "false").upper() == "TRUE"
           and all_creds.get(k, "").strip().upper() == "FINNHUB"
    ]
    if not provider_indices:
        return "", ""
    idx = provider_indices[0]
    api_key = all_creds.get(f"SCREENER_API_KEY_{idx}", "") or all_creds.get(f"SCREENER_TOKEN_{idx}", "")
    api_url = all_creds.get(f"SCREENER_URL_{idx}", "https://finnhub.io/api/v1/")
    return api_key, api_url

def get_vix_value():
    """
    Fetches the current VIX index value from Finnhub.
    Caches result for CACHE_DURATION to reduce API calls.
    Returns float or None.
    """
    global _vix_cache
    current_time = time.time()

    if _vix_cache["value"] is not None and (current_time - _vix_cache["timestamp"] < CACHE_DURATION):
        return _vix_cache["value"]

    api_key, api_url = get_finnhub_api_params()
    if not api_key:
        log_error("[vix_gatekeeper] SCREENER_API_KEY is missing from encrypted screener credentials.", module="vix_gatekeeper")
        return None

    try:
        response = requests.get(
            f"{api_url.rstrip('/')}/quote?symbol=^VIX&token={api_key}"
        )
        response.raise_for_status()
        data = response.json()
        vix = float(data.get("c", 0))
        _vix_cache = {"value": vix, "timestamp": current_time}
        log_debug(f"[vix_gatekeeper] Current VIX: {vix}", module="vix_gatekeeper")
        return vix
    except Exception as e:
        log_error(f"[vix_gatekeeper] Failed to fetch VIX: {e}", module="vix_gatekeeper")
        return None

def is_vix_above_threshold(threshold: float) -> bool:
    """
    Returns True if VIX is greater than or equal to threshold.
    Used by strategy_close to block trades in low-volatility environments.
    """
    vix = get_vix_value()
    if vix is None:
        log_debug("[vix_gatekeeper] Could not retrieve VIX, defaulting to allow trade.", module="vix_gatekeeper")
        return True  # Fail open
    return vix >= threshold
