# tbot_bot/screeners/finnhub_screener.py
# summary: Screens symbols using Finnhub price, volume, and VWAP data (strategy-specific filters, TEST_MODE aware)

import requests
import time
import json
from datetime import datetime
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support.path_resolver import get_output_path
from pathlib import Path

config = get_bot_config()

FINNHUB_API_KEY = decrypt_json("screener_api").get("FINNHUB_API_KEY", "")
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()

EXCHANGES = config.get("EXCHANGES", "US").split(",")
BOT_ID = None
try:
    from tbot_bot.support.utils_identity import get_bot_identity
    BOT_ID = get_bot_identity()
except Exception:
    BOT_ID = None

STRIKE_FILE = get_output_path(bot_identity=BOT_ID, category="screeners", filename="exclusion_strikes.json")
HARD_EXCLUSION_FILE = get_output_path(bot_identity=BOT_ID, category="screeners", filename="hard_exclusion_list.json")
STRIKE_THRESHOLD = int(config.get("STRIKE_THRESHOLD", 5))
API_TIMEOUT = int(config.get("API_TIMEOUT", 30))

MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)

# Replace TEST_MODE config flag with runtime detection of test_mode.flag
CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

session_exclusions = set()
strike_counts = {}
hard_exclusions = set()

def log(msg):
    if LOG_LEVEL == "verbose":
        print(msg)

def load_state():
    global strike_counts, hard_exclusions
    try:
        with open(STRIKE_FILE, "r") as f:
            strike_counts = json.load(f)
    except:
        strike_counts = {}
    try:
        with open(HARD_EXCLUSION_FILE, "r") as f:
            hard_exclusions = set(json.load(f))
    except:
        hard_exclusions = set()

def save_state():
    with open(STRIKE_FILE, "w") as f:
        json.dump(strike_counts, f, indent=2)
    with open(HARD_EXCLUSION_FILE, "w") as f:
        json.dump(list(hard_exclusions), f, indent=2)

def mark_failed(symbol):
    session_exclusions.add(symbol)
    strike_counts[symbol] = strike_counts.get(symbol, 0) + 1
    if strike_counts[symbol] >= STRIKE_THRESHOLD:
        hard_exclusions.add(symbol)

def get_symbol_list():
    url = f"https://finnhub.io/api/v1/stock/symbol?exchange={','.join(EXCHANGES)}&token={FINNHUB_API_KEY}"
    try:
        resp = requests.get(url, timeout=API_TIMEOUT)
        if resp.status_code != 200:
            raise Exception("Failed to get symbols from Finnhub")
        return [s["symbol"] for s in resp.json() if "." not in s["symbol"]]
    except Exception as e:
        log(f"Error fetching symbol list: {e}")
        return []

def get_quote(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    try:
        resp = requests.get(url, timeout=API_TIMEOUT)
        if resp.status_code != 200:
            mark_failed(symbol)
            return None
        data = resp.json()
        if "c" in data and "o" in data and "vwap" in data and data["c"] and data["o"] and data["vwap"]:
            return data
        else:
            mark_failed(symbol)
            return None
    except Exception as e:
        mark_failed(symbol)
        log(f"Error fetching quote for {symbol}: {e}")
        return None

def get_market_cap(symbol):
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}"
    try:
        resp = requests.get(url, timeout=API_TIMEOUT)
        if resp.status_code == 200:
            return resp.json().get("marketCapitalization", None)
        else:
            mark_failed(symbol)
            return None
    except Exception as e:
        mark_failed(symbol)
        log(f"Error fetching market cap for {symbol}: {e}")
        return None

def get_filtered_stocks(limit=3, strategy="open", skip_volume=False):
    """
    TEST_MODE: Ignores all filters except price, returns first 3 passing.
    Non-TEST_MODE: Applies all normal filters.
    """
    load_state()
    all_symbols = get_symbol_list()
    log(f"Fetched {len(all_symbols)} total symbols")
    results = []

    gap_key = f"MAX_GAP_PCT_{strategy.upper()}"
    min_cap_key = f"MIN_MARKET_CAP_{strategy.upper()}"
    max_cap_key = f"MAX_MARKET_CAP_{strategy.upper()}"

    max_gap = float(config.get(gap_key, 0.1))
    min_cap = float(config.get(min_cap_key, 2e9))
    max_cap = float(config.get(max_cap_key, 1e10))

    test_mode_active = is_test_mode_active()

    for idx, symbol in enumerate(all_symbols):
        if symbol in session_exclusions or symbol in hard_exclusions:
            log_event("screener", f"Excluded symbol: {symbol}")
            continue

        quote = get_quote(symbol)
        if not quote:
            log_event("screener", f"Rejected: No valid quote for {symbol}")
            continue

        current = float(quote["c"])
        open_ = float(quote["o"])
        vwap = float(quote["vwap"])

        if current <= 0 or open_ <= 0 or vwap <= 0:
            log_event("screener", f"Rejected: Invalid quote data for {symbol}")
            continue

        # TEST_MODE: Only price filter
        if test_mode_active:
            if current < MIN_PRICE or (current > MAX_PRICE and not FRACTIONAL):
                log_event("screener", f"Rejected: Price out of bounds for {symbol} = {current}")
                continue
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": abs(current - open_) / open_
            })
            if len(results) >= limit:
                break
            continue

        if current < MIN_PRICE:
            log_event("screener", f"Rejected: Price below MIN_PRICE for {symbol} = {current}")
            continue
        if current > MAX_PRICE and not FRACTIONAL:
            log_event("screener", f"Rejected: Price exceeds MAX_PRICE and FRACTIONAL disabled for {symbol} = {current}")
            continue

        market_cap = get_market_cap(symbol)
        if not (market_cap and min_cap <= market_cap <= max_cap):
            log_event("screener", f"Rejected: Market cap out of range for {symbol} = {market_cap}")
            continue

        gap = abs((current - open_) / open_)
        if gap > max_gap:
            log_event("screener", f"Rejected: Gap {gap:.2%} > max {max_gap:.2%} for {symbol}")
            continue

        momentum = abs(current - open_) / open_
        results.append({
            "symbol": symbol,
            "price": current,
            "vwap": vwap,
            "momentum": momentum
        })

        if idx % 50 == 0:
            log(f"Checked {idx} symbols...")
        time.sleep(1.0)

    if not test_mode_active:
        results.sort(key=lambda x: x["momentum"], reverse=True)
        top = results[:limit]
    else:
        top = results[:limit]
    log_event("screener", f"Selected top {len(top)} candidates from {len(all_symbols)}")
    save_state()
    return top
