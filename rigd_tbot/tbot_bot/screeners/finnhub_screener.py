# tbot_bot/screeners/finnhub_screener.py
# summary: Screens symbols using Finnhub price, volume, and VWAP data (strategy-specific filters, TEST_MODE aware)
# Updated: Uses cached universe and quote-only fetches per TradeBot specification

import requests
import time
from pathlib import Path
from tbot_bot.screeners.screener_base import ScreenerBase
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.config.env_bot import get_bot_config

config = get_bot_config()
FINNHUB_API_KEY = decrypt_json("screener_api").get("FINNHUB_API_KEY", "")
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()
API_TIMEOUT = int(config.get("API_TIMEOUT", 30))
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)
CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def log(msg):
    if LOG_LEVEL == "verbose":
        print(msg)

class FinnhubScreener(ScreenerBase):
    """
    Finnhub screener: loads eligible symbols from universe cache,
    fetches latest quotes from Finnhub, filters per strategy, test mode aware.
    """
    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using Finnhub API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        for idx, symbol in enumerate(symbols):
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            try:
                resp = requests.get(url, timeout=API_TIMEOUT)
                if resp.status_code != 200:
                    log(f"Error fetching quote for {symbol}: {resp.status_code}")
                    continue
                data = resp.json()
                # Finnhub: c = current, o = open, vwap = vwap (or calc)
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
            if idx % 50 == 0:
                log(f"Fetched {idx} quotes...")
            time.sleep(0.2)
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

        results = []
        for q in quotes:
            symbol = q["symbol"]
            current = float(q.get("c", 0))
            open_ = float(q.get("o", 0))
            vwap = float(q.get("vwap", 0))

            if current <= 0 or open_ <= 0 or vwap <= 0:
                continue

            if test_mode_active:
                if current < MIN_PRICE or (current > MAX_PRICE and not FRACTIONAL):
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
                continue
            if current > MAX_PRICE and not FRACTIONAL:
                continue

            # Market cap can only be filtered if included in universe, else skip

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

# Usage example:
# screener = FinnhubScreener()
# candidates = screener.run_screen()
