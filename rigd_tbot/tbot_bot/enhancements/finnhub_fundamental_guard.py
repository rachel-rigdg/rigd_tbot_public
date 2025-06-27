# tbot_bot/enhancements/finnhub_fundamental_guard.py
# Enhancement: Blocks trades if company fundamentals fail configured thresholds (e.g. P/E, debt/equity)
# Requires: SCREENER_API_KEY loaded via secrets, cache path: data/cache/fundamentals_{date}.json

import os
import json
import datetime
import requests
from tbot_bot.support.utils_log import log_event  # UPDATED
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.decrypt_secrets import get_decrypted_json
from tbot_bot.support.path_resolver import get_cache_path  # <- Surgical update: path resolver used

# Load config and API key
config = get_bot_config()
SCREENER_API = get_decrypted_json("storage/secrets/screener_api.json.enc")
SCREENER_API_KEY = SCREENER_API.get("SCREENER_API_KEY", "") or SCREENER_API.get("FINNHUB_API_KEY", "")
SCREENER_URL = SCREENER_API.get("SCREENER_URL", "https://finnhub.io/api/v1/")
FUNDAMENTAL_CACHE = get_cache_path(f"fundamentals_{datetime.date.today()}.json")  # <- Surgical update: path resolver used

# Runtime filter toggles
ENABLE_FUNDAMENTAL_GUARD = config.get("ENABLE_FUNDAMENTAL_GUARD", "true").lower() == "true"
MAX_DEBT_EQUITY = float(config.get("MAX_DEBT_EQUITY", 2.5))
MAX_PE_RATIO = float(config.get("MAX_PE_RATIO", 50.0))
MIN_MARKET_CAP = int(config.get("MIN_MARKET_CAP_FUNDAMENTAL", 2000000000))


def load_cache():
    if os.path.exists(FUNDAMENTAL_CACHE):
        with open(FUNDAMENTAL_CACHE, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(FUNDAMENTAL_CACHE), exist_ok=True)
    with open(FUNDAMENTAL_CACHE, "w") as f:
        json.dump(cache, f)


def fetch_fundamentals(symbol: str) -> dict:
    url = f"{SCREENER_URL.rstrip('/')}/stock/metric?symbol={symbol}&metric=all&token={SCREENER_API_KEY}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("metric", {})
    except Exception as e:
        log_event(f"FUNDAMENTAL_FETCH_ERROR: symbol={symbol} error={str(e)}")
    return {}


def passes_fundamental_guard(symbol: str, context: dict = None) -> bool:
    """
    Validates symbol against PE ratio, D/E ratio, and market cap requirements.
    Rejects if any metric fails. Logs rejections.
    """
    if not ENABLE_FUNDAMENTAL_GUARD or not SCREENER_API_KEY:
        return True

    cache = load_cache()
    if symbol in cache:
        data = cache[symbol]
    else:
        data = fetch_fundamentals(symbol)
        cache[symbol] = data
        save_cache(cache)

    try:
        pe = float(data.get("peNormalizedAnnual", 0))
        debt_equity = float(data.get("totalDebt/totalEquityAnnual", 0))
        market_cap = float(data.get("marketCapitalization", 0))
    except Exception:
        log_event(f"FUNDAMENTAL_PARSE_FAIL: {symbol} raw={data}")
        return False

    if pe > MAX_PE_RATIO or debt_equity > MAX_DEBT_EQUITY or market_cap < MIN_MARKET_CAP:
        log_event(
            f"FUNDAMENTAL_REJECTED: {symbol} | P/E={pe:.1f} D/E={debt_equity:.2f} Cap=${market_cap:,.0f} "
            f"| context={context}"
        )
        return False

    return True
