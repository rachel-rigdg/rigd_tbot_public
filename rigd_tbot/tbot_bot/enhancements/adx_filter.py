# tbot_bot/enhancements/adx_filter.py
# Blocks mid-session trades during trending ADX conditions
# ------------------------------------------------------
# Blocks VWAP mean reversion trades when ADX is high (strong trend)
# Used by: strategy_mid.py, risk_module.py

from typing import Optional, Tuple
import requests
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.utils_log import log_debug

ADX_FILTER_THRESHOLD = 25  # Block trades if ADX > this

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

def get_adx(symbol: str, resolution: str = "5", length: int = 14) -> Optional[float]:
    """
    Fetches ADX value for the symbol from Finnhub.
    Returns latest ADX as float, or None if unavailable/error.
    Never raises.
    """
    try:
        api_key, api_url = get_finnhub_api_params()
        if not api_key:
            log_debug("[adx_filter] Finnhub API key missing.")
            return None
        url = (
            f"{api_url.rstrip('/')}/indicator"
            f"?symbol={symbol}&resolution={resolution}&indicator=adx"
            f"&timeperiod={length}&token={api_key}"
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
