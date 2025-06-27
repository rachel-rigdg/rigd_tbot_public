# tbot_bot/enhancements/bollinger_confluence.py
# Confirms entries using Bollinger band alignment

from typing import Optional
import requests
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_debug  # UPDATED

config = get_bot_config()
SCREENER_API_KEY = config.get("SCREENER_API_KEY", "") or config.get("FINNHUB_API_KEY", "")
SCREENER_URL = config.get("SCREENER_URL", "https://finnhub.io/api/v1/")
BBANDS_STD_DEV = 2  # Number of standard deviations for Bollinger Bands

def get_bollinger_bands(symbol: str, resolution: str = "5", length: int = 20) -> Optional[dict]:
    """
    Fetches Bollinger Bands data for the symbol from Finnhub.
    Returns a dictionary with upper, lower, and mid bands.
    """
    try:
        url = (
            f"{SCREENER_URL.rstrip('/')}/indicator"
            f"?symbol={symbol}&resolution={resolution}&indicator=bbands"
            f"&timeperiod={length}&nbdevup={BBANDS_STD_DEV}&nbdevdn={BBANDS_STD_DEV}"
            f"&token={SCREENER_API_KEY}"
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
