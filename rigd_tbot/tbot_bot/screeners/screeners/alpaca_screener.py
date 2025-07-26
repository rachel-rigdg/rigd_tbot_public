# tbot_bot/screeners/screeners/alpaca_screener.py
# Loads screener credentials where TRADING_ENABLED == "true" and PROVIDER == "ALPACA" per spec.
# Uses ONLY generic SCREENER_ keys—never BROKER_—and never reads internal env for credentials.

import requests
import time
from tbot_bot.screeners.screener_base import ScreenerBase
from tbot_bot.screeners.screener_utils import load_universe_cache
from tbot_bot.screeners.screener_filter import filter_symbols as core_filter_symbols
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.utils_log import log_event
from tbot_bot.trading.risk_module import validate_trade

def get_trading_screener_creds():
    """
    Loads screener credentials where TRADING_ENABLED == 'true' and PROVIDER == 'ALPACA'.
    Returns dict of keys for the first enabled ALPACA provider.
    """
    all_creds = load_screener_credentials()
    candidates = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
        and all_creds.get(f"TRADING_ENABLED_{k.split('_')[-1]}", "false").lower() == "true"
        and all_creds.get(k, "").strip().upper() == "ALPACA"
    ]
    if not candidates:
        return {}
    idx = candidates[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

config = get_bot_config()
screener_creds = None  # Do not load credentials at import time

def get_screener_creds_runtime():
    global screener_creds
    if screener_creds is None:
        screener_creds = get_trading_screener_creds()
    return screener_creds

def get_header_and_vars():
    creds = get_screener_creds_runtime()
    SCREENER_API_KEY = creds.get("SCREENER_API_KEY", "")
    SCREENER_SECRET_KEY = creds.get("SCREENER_SECRET_KEY", "")
    SCREENER_USERNAME = creds.get("SCREENER_USERNAME", "")
    SCREENER_PASSWORD = creds.get("SCREENER_PASSWORD", "")
    SCREENER_URL = creds.get("SCREENER_URL", "https://data.alpaca.markets")
    SCREENER_TOKEN = creds.get("SCREENER_TOKEN", "")
    HEADERS = {
        "APCA-API-KEY-ID": SCREENER_API_KEY,
        "APCA-API-SECRET-KEY": SCREENER_SECRET_KEY,
        "Authorization": f"Bearer {SCREENER_TOKEN}" if SCREENER_TOKEN else ""
    }
    return HEADERS, SCREENER_USERNAME, SCREENER_PASSWORD, SCREENER_URL

API_TIMEOUT = int(config.get("API_TIMEOUT", 30))
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()

def log(msg):
    if LOG_LEVEL == "verbose":
        print(f"[Alpaca Screener] {msg}")

class AlpacaScreener(ScreenerBase):
    """
    Alpaca screener: loads eligible symbols from universe cache,
    fetches latest quotes from Alpaca, filters per strategy.
    Ensures output always flags fractional eligibility.
    """
    def __init__(self, *args, strategy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.strategy = strategy

    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using Alpaca API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        HEADERS, SCREENER_USERNAME, SCREENER_PASSWORD, SCREENER_URL = get_header_and_vars()
        for idx, symbol in enumerate(symbols):
            url_bars = f"{SCREENER_URL.rstrip('/')}/v2/stocks/{symbol}/bars?timeframe=1Day&limit=1"
            auth = (SCREENER_USERNAME, SCREENER_PASSWORD) if SCREENER_USERNAME and SCREENER_PASSWORD else None
            try:
                bars_resp = requests.get(url_bars, headers={k: v for k, v in HEADERS.items() if v}, timeout=API_TIMEOUT, auth=auth)
                if bars_resp.status_code != 200:
                    log(f"Error fetching bars for {symbol}: HTTP {bars_resp.status_code}")
                    continue
                bars = bars_resp.json().get("bars", [])
                if not bars:
                    log(f"No bars data for {symbol}")
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
            if idx % 50 == 0 and idx > 0:
                log(f"Fetched {idx} quotes...")
            time.sleep(0.2)
        return quotes

    def run_screen(self, pool_size=15):
        """
        Returns the full, ranked pool of symbol candidates (not filtered by final cut).
        pool_size: number of symbols to return (CANDIDATE_MULTIPLIER x MAX_TRADES from strategy).
        """
        universe = load_universe_cache()
        all_symbols = [s["symbol"] for s in universe][:pool_size * 2]
        quotes = self.fetch_live_quotes(all_symbols)
        strategy = self.strategy or self.env.get("STRATEGY_NAME", "open")
        gap_key = f"MAX_GAP_PCT_{strategy.upper()}"
        min_cap_key = f"MIN_MARKET_CAP_{strategy.upper()}"
        max_cap_key = f"MAX_MARKET_CAP_{strategy.upper()}"
        max_gap = float(self.env.get(gap_key, 0.1))
        min_cap = float(self.env.get(min_cap_key, 2e9))
        max_cap = float(self.env.get(max_cap_key, 1e10))

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
            is_fractional = bool(universe_cache.get(symbol, {}).get("isFractional", FRACTIONAL))
            mc_millions = mc / 1_000_000 if mc else 0
            price_candidates.append({
                "symbol": symbol,
                "lastClose": current,
                "marketCap": mc_millions,
                "exchange": exch,
                "isFractional": is_fractional,
                "price": current,
                "vwap": vwap,
                "open": open_
            })

        filtered = core_filter_symbols(
            price_candidates,
            min_price=MIN_PRICE,
            max_price=MAX_PRICE,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            max_size=pool_size * 2
        )

        results = []
        open_positions_count = 0  # Should be fetched from runtime if possible
        account_balance = float(self.env.get("ACCOUNT_BALANCE", 0))
        signal_index = 0
        total_signals = pool_size

        for q in price_candidates:
            if not any(f["symbol"] == q["symbol"] for f in filtered):
                continue
            symbol = q["symbol"]
            current = q["price"]
            open_ = q["open"]
            vwap = q["vwap"]
            gap = abs((current - open_) / open_) if open_ else 0
            if gap > max_gap:
                continue
            valid, reason_or_alloc = validate_trade(
                symbol=symbol,
                side="long",
                account_balance=account_balance,
                open_positions_count=open_positions_count,
                signal_index=signal_index,
                total_signals=total_signals
            )
            if not valid:
                continue
            momentum = abs(current - open_) / open_
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
            signal_index += 1

        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("alpaca_screener", f"run_screen returned {len(results[:pool_size])} candidates")
        return results[:pool_size]

    def filter_candidates(self, quotes):
        """
        DEPRECATED: Returns a filtered, sorted candidate list for legacy modules.
        """
        strategy = self.strategy or self.env.get("STRATEGY_NAME", "open")
        gap_key = f"MAX_GAP_PCT_{strategy.upper()}"
        min_cap_key = f"MIN_MARKET_CAP_{strategy.upper()}"
        max_cap_key = f"MAX_MARKET_CAP_{strategy.upper()}"
        max_gap = float(self.env.get(gap_key, 0.1))
        min_cap = float(self.env.get(min_cap_key, 2e9))
        max_cap = float(self.env.get(max_cap_key, 1e10))
        limit = int(self.env.get("SCREENER_LIMIT", 3))

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
            is_fractional = bool(universe_cache.get(symbol, {}).get("isFractional", FRACTIONAL))
            mc_millions = mc / 1_000_000 if mc else 0
            price_candidates.append({
                "symbol": symbol,
                "lastClose": current,
                "marketCap": mc_millions,
                "exchange": exch,
                "is_fractional": is_fractional,
                "price": current,
                "vwap": vwap,
                "open": open_
            })

        filtered = core_filter_symbols(
            price_candidates,
            min_price=MIN_PRICE,
            max_price=MAX_PRICE,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            max_size=limit
        )

        results = []
        open_positions_count = 0  # Should be fetched from runtime if possible
        account_balance = float(self.env.get("ACCOUNT_BALANCE", 0))
        signal_index = 0
        total_signals = limit

        for q in price_candidates:
            if not any(f["symbol"] == q["symbol"] for f in filtered):
                continue
            symbol = q["symbol"]
            current = q["price"]
            open_ = q["open"]
            vwap = q["vwap"]
            gap = abs(current - open_) / open_ if open_ else 0
            if gap > max_gap:
                continue
            valid, reason_or_alloc = validate_trade(
                symbol=symbol,
                side="long",
                account_balance=account_balance,
                open_positions_count=open_positions_count,
                signal_index=signal_index,
                total_signals=total_signals
            )
            if not valid:
                continue
            momentum = abs(current - open_) / open_
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
            signal_index += 1

        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("alpaca_screener", f"filter_candidates returned {len(results)} candidates (legacy mode)")
        return results
