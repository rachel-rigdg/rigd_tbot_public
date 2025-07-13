# tbot_bot/screeners/screeners/finnhub_screener.py
# Loads screener credentials where TRADING_ENABLED == "true" and PROVIDER == "FINNHUB" per central flag.
# Uses only enabled providers for active (strategy) screener operation. 100% generic screener keys.

import requests
import time
from pathlib import Path
from tbot_bot.screeners.screener_base import ScreenerBase
from tbot_bot.screeners.screener_filter import filter_symbols as core_filter_symbols
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.screeners.screener_utils import load_universe_cache
from tbot_bot.support.secrets_manager import load_screener_credentials

def get_trading_screener_creds():
    # Only use providers with TRADING_ENABLED == "true" and PROVIDER == "FINNHUB"
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"TRADING_ENABLED_{k.split('_')[-1]}", "false").upper() == "TRUE"
           and all_creds.get(k, "").strip().upper() == "FINNHUB"
    ]
    if not provider_indices:
        raise RuntimeError("No FINNHUB screener providers enabled for active trading. Please enable at least one in the credential admin.")
    idx = provider_indices[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

config = get_bot_config()
screener_creds = get_trading_screener_creds()
SCREENER_API_KEY = (
    screener_creds.get("SCREENER_API_KEY", "")
    or screener_creds.get("SCREENER_TOKEN", "")
)
SCREENER_URL = screener_creds.get("SCREENER_URL", "https://finnhub.io/api/v1/")
SCREENER_USERNAME = screener_creds.get("SCREENER_USERNAME", "")
SCREENER_PASSWORD = screener_creds.get("SCREENER_PASSWORD", "")
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()
API_TIMEOUT = int(config.get("API_TIMEOUT", 30))
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)
STRATEGY_SLEEP_TIME = float(config.get("STRATEGY_SLEEP_TIME", 0.03))
CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def log(msg):
    if LOG_LEVEL == "verbose":
        print(f"[Finnhub Screener] {msg}")

class FinnhubScreener(ScreenerBase):
    """
    Finnhub screener: loads eligible symbols from universe cache,
    fetches latest quotes from Finnhub API using screener credentials,
    filters per strategy, test mode aware.
    """
    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using Finnhub API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        for idx, symbol in enumerate(symbols):
            url = f"{SCREENER_URL.rstrip('/')}/quote?symbol={symbol}&token={SCREENER_API_KEY}"
            auth = (SCREENER_USERNAME, SCREENER_PASSWORD) if SCREENER_USERNAME and SCREENER_PASSWORD else None
            try:
                resp = requests.get(url, timeout=API_TIMEOUT, auth=auth)
                if resp.status_code != 200:
                    log(f"Error fetching quote for {symbol}: HTTP {resp.status_code}")
                    continue
                data = resp.json()
                c = float(data.get("c", 0))
                o = float(data.get("o", 0))
                vwap = float(data.get("vwap", 0)) if "vwap" in data and data.get("vwap", 0) else (c if c else 0)
                quotes.append({
                    "symbol": symbol,
                    "c": c,
                    "o": o,
                    "vwap": vwap
                })
            except Exception as e:
                log(f"Exception fetching quote for {symbol}: {e}")
                continue
            if idx % 50 == 0 and idx > 0:
                log(f"Fetched {idx} quotes...")
            time.sleep(STRATEGY_SLEEP_TIME)
        return quotes

    def filter_candidates(self, quotes):
        """
        Filters the list of quote dicts using price, gap, and other rules.
        TEST_MODE: Only price filter, returns first N passing.
        Returns eligible symbol dicts.
        """
        strategy = self.env.get("STRATEGY_NAME", "open")
        gap_key = f"MAX_GAP_PCT_{strategy.upper()}"
        min_cap_key = f"MIN_MARKET_CAP_{strategy.upper()}"
        max_cap_key = f"MAX_MARKET_CAP_{strategy.upper()}"
        max_gap = float(self.env.get(gap_key, 0.1))
        min_cap = float(self.env.get(min_cap_key, 2e9))
        max_cap = float(self.env.get(max_cap_key, 1e10))
        limit = int(self.env.get("SCREENER_LIMIT", 3))
        test_mode_active = is_test_mode_active()

        try:
            universe_cache = {s["symbol"]: s for s in load_universe_cache()}
        except Exception:
            universe_cache = {}

        price_candidates = []
        for q in quotes:
            symbol = q["symbol"]
            current = float(q.get("c", 0))
            open_ = float(q.get("o", 0))
            vwap = float(q.get("vwap", 0))
            if current <= 0 or open_ <= 0 or vwap <= 0:
                continue
            mc = universe_cache.get(symbol, {}).get("marketCap", 0)
            exch = universe_cache.get(symbol, {}).get("exchange", "US")
            is_fractional = universe_cache.get(symbol, {}).get("isFractional", None)
            price_candidates.append({
                "symbol": symbol,
                "lastClose": current,
                "marketCap": mc,
                "exchange": exch,
                "isFractional": is_fractional,
                "price": current,
                "vwap": vwap,
                "open": open_
            })

        filtered = core_filter_symbols(
            price_candidates,
            exchanges=["US"],
            min_price=MIN_PRICE,
            max_price=MAX_PRICE,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            blocklist=None,
            max_size=limit
        )

        results = []
        for q in price_candidates:
            if not any(f["symbol"] == q["symbol"] for f in filtered):
                continue
            symbol = q["symbol"]
            current = q["price"]
            open_ = q["open"]
            vwap = q["vwap"]

            if test_mode_active:
                results.append({
                    "symbol": symbol,
                    "price": current,
                    "vwap": vwap,
                    "momentum": abs(current - open_) / open_
                })
                if len(results) >= limit:
                    break
                continue

            gap = abs((current - open_) / open_)
            if gap > max_gap:
                continue

            momentum = abs(current - open_) / open_
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": momentum
            })

        if not test_mode_active:
            results.sort(key=lambda x: x["momentum"], reverse=True)
            return results[:limit]
        else:
            return results[:limit]
