# tbot_bot/enhancements/bollinger_confluence.py
# Confirms entries using Bollinger band alignment

from typing import Optional
import requests
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.utils_log import log_debug  # UPDATED

BBANDS_STD_DEV = 2  # Number of standard deviations for Bollinger Bands

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

def get_bollinger_bands(symbol: str, resolution: str = "5", length: int = 20) -> Optional[dict]:
    """
    Fetches Bollinger Bands data for the symbol from Finnhub.
    Returns a dictionary with upper, lower, and mid bands.
    """
    try:
        api_key, api_url = get_finnhub_api_params()
        if not api_key:
            log_debug("[bollinger_confluence] Finnhub API key missing.")
            return None
        url = (
            f"{api_url.rstrip('/')}/indicator"
            f"?symbol={symbol}&resolution={resolution}&indicator=bbands"
            f"&timeperiod={length}&nbdevup={BBANDS_STD_DEV}&nbdevdn={BBANDS_STD_DEV}"
            f"&token={api_key}"
        )
        resp = requests.get(url)
        data = resp.json()

        if "bbands" in data and all(key in data["bbands"] for key in ["upperband", "lowerband", "real"]):
            upper = data["bbands"]["upperband"][-1]
            lower = data["bbands"]["lowerband"][-1]
            real = data["bbands"]["real"][-1]
            log_debug(f"[bollinger_confluence] BB for {symbol}: upper={upper}, lower={lower}, price={real}")
            return {"upper": upper, "lower": lower, "price": real}
    except Exception as e:
        log_debug(f"[bollinger_confluence] Error fetching BB for {symbol}: {e}")

    return None

def confirm_bollinger_touch(symbol: str, direction: str) -> bool:
    """
    Confirms if the current price touched the appropriate Bollinger Band.
    direction = 'long' checks lower band touch
    direction = 'short' checks upper band touch
    Returns True if confirmed, False otherwise
    """
    bb = get_bollinger_bands(symbol)
    if not bb:
        return True  # Fallback: allow trade if BB data is unavailable

    if direction == "long":
        return bb["price"] <= bb["lower"]
    elif direction == "short":
        return bb["price"] >= bb["upper"]
    return True
