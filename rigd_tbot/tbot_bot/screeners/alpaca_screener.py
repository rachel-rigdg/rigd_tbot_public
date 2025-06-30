# tbot_bot/screeners/alpaca_screener.py
# summary: Screens symbols using Alpaca price, volume, and VWAP data (strategy-specific filters)
# Updated: Supports BROKER_USERNAME, BROKER_PASSWORD, BROKER_URL, and agnostic variable handling per latest spec

import requests
import time
from tbot_bot.screeners.screener_base import ScreenerBase
from tbot_bot.screeners.screener_utils import get_screener_secrets, load_universe_cache
from tbot_bot.screeners.screener_filter import filter_symbols as core_filter_symbols
from tbot_bot.config.env_bot import get_bot_config

config = get_bot_config()
broker_creds = get_screener_secrets()
ALPACA_API_KEY = broker_creds.get("BROKER_API_KEY", "")
ALPACA_SECRET_KEY = broker_creds.get("BROKER_SECRET_KEY", "")
BROKER_USERNAME = broker_creds.get("BROKER_USERNAME", "")
BROKER_PASSWORD = broker_creds.get("BROKER_PASSWORD", "")
BROKER_URL = broker_creds.get("BROKER_URL", "https://data.alpaca.markets")
BROKER_TOKEN = broker_creds.get("BROKER_TOKEN", "")
HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "Authorization": f"Bearer {BROKER_TOKEN}" if BROKER_TOKEN else ""
}
API_TIMEOUT = int(config.get("API_TIMEOUT", 30))
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()

def log(msg):
    if LOG_LEVEL == "verbose":
        print(msg)

class AlpacaScreener(ScreenerBase):
    """
    Alpaca screener: loads eligible symbols from universe cache,
    fetches latest quotes from Alpaca, filters per strategy.
    """
    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using Alpaca API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        for idx, symbol in enumerate(symbols):
            url_bars = f"{BROKER_URL.rstrip('/')}/v2/stocks/{symbol}/bars?timeframe=1Day&limit=1"
            auth = (BROKER_USERNAME, BROKER_PASSWORD) if BROKER_USERNAME and BROKER_PASSWORD else None
            try:
                bars_resp = requests.get(url_bars, headers={k: v for k, v in HEADERS.items() if v}, timeout=API_TIMEOUT, auth=auth)
                if bars_resp.status_code != 200:
                    log(f"Error fetching bars for {symbol}: status {bars_resp.status_code}")
                    continue
                bars = bars_resp.json().get("bars", [])
                if not bars:
                    log(f"No bars found for {symbol}")
                    continue
                bar = bars[0]
                current = float(bar.get("c", 0))
                open_ = float(bar.get("o", 0))
                vwap = (bar["h"] + bar["l"] + bar["c"]) / 3 if all(k in bar for k in ("h", "l", "c")) else current
                quotes.append({
                    "symbol": symbol,
                    "c": current,
                    "o": open_,
                    "vwap": vwap
                })
            except Exception as e:
                log(f"Exception fetching quote for {symbol}: {e}")
                continue
            if idx % 50 == 0:
                log(f"Fetched {idx} quotes...")
            time.sleep(0.2)  # throttle to avoid API limits
        return quotes

    def filter_candidates(self, quotes):
        """
        Filters the list of quote dicts using price, gap, and other rules.
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

        # Use marketCap, exchange, isFractional from universe cache if available
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
        results.sort(key=lambda x: x["momentum"], reverse=True)
        return results
