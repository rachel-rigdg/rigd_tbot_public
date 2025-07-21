# tbot_bot/enhancements/finnhub_fundamental_guard.py
# Enhancement: Blocks trades if company fundamentals fail configured thresholds (e.g. P/E, debt/equity)
# Requires: SCREENER_API_KEY loaded via secrets, cache path: data/cache/fundamentals_{date}.json

import os
import json
import datetime
import requests
from tbot_bot.support.utils_log import log_event  # UPDATED
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.path_resolver import get_cache_path  # <- Surgical update: path resolver used
from tbot_bot.config.env_bot import get_bot_config

# Load config
config = get_bot_config()
# Credential loader (never hardcode, always use secrets manager)
def get_finnhub_api_params():
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"TRADING_ENABLED_{k.split('_')[-1]}", "false").upper() == "TRUE"
           and all_creds.get(k, "").strip().upper() == "FINNHUB"
    ]
    if not provider_indices:
        return "", "", "", ""
    idx = provider_indices[0]
    api_key = all_creds.get(f"SCREENER_API_KEY_{idx}", "") or all_creds.get(f"SCREENER_TOKEN_{idx}", "")
    api_url = all_creds.get(f"SCREENER_URL_{idx}", "https://finnhub.io/api/v1/")
    username = all_creds.get(f"SCREENER_USERNAME_{idx}", "")
    password = all_creds.get(f"SCREENER_PASSWORD_{idx}", "")
    return api_key, api_url, username, password

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
    api_key, api_url, username, password = get_finnhub_api_params()
    if not api_key:
        log_event(f"FUNDAMENTAL_FETCH_ERROR: symbol={symbol} error=missing_api_key", "finnhub_fundamental_guard")
        return {}
    url = f"{api_url.rstrip('/')}/stock/metric?symbol={symbol}&metric=all&token={api_key}"
    auth = (username, password) if username and password else None
    try:
        resp = requests.get(url, timeout=5, auth=auth)
        if resp.status_code == 200:
            return resp.json().get("metric", {})
    except Exception as e:
        log_event(f"FUNDAMENTAL_FETCH_ERROR: symbol={symbol} error={str(e)}", "finnhub_fundamental_guard")
    return {}


def passes_fundamental_guard(symbol: str, context: dict = None) -> bool:
    """
    Validates symbol against PE ratio, D/E ratio, and market cap requirements.
    Rejects if any metric fails. Logs rejections.
    """
    api_key, _, _, _ = get_finnhub_api_params()
    if not ENABLE_FUNDAMENTAL_GUARD or not api_key:
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
        log_event(f"FUNDAMENTAL_PARSE_FAIL: {symbol} raw={data}", "finnhub_fundamental_guard")
        return False

    if pe > MAX_PE_RATIO or debt_equity > MAX_DEBT_EQUITY or market_cap < MIN_MARKET_CAP:
        log_event(
            f"FUNDAMENTAL_REJECTED: {symbol} | P/E={pe:.1f} D/E={debt_equity:.2f} Cap=${market_cap:,.0f} "
            f"| context={context}",
            "finnhub_fundamental_guard"
        )
        return False

    return True
