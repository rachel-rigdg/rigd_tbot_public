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
from tbot_bot.support.utils_log import log_event

# --- NEW (surgical): safe cache helpers for auto-heal + stale handling ---
from tbot_bot.screeners.screener_utils import (
    safe_load_universe_cache,  # returns None on parse/shape errors and quarantines bad cache
)

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

def _parse_test_universe():
    raw = str(config.get("SCREENER_TEST_MODE_UNIVERSE", "")).strip()
    if not raw:
        return []
    parts = [p.strip().upper() for p in raw.replace(",", " ").split() if p.strip()]
    return list(dict.fromkeys(parts))

def log(msg):
    if LOG_LEVEL == "verbose":
        print(f"[Finnhub Screener] {msg}")

def _normalize_price_fields(c, o, vwap):
    # Correct for possible cents-vs-dollars mis-scaling from API
    if max(c or 0, o or 0, vwap or 0) > 10000:
        return (c / 100 if c else 0, o / 100 if o else 0, vwap / 100 if vwap else 0)
    return (c, o, vwap)

# --- NEW (surgical): helper to load universe symbols with auto-rebuild + fallback ---
def _get_universe_symbols(max_pool: int) -> list[str]:
    """
    Returns up to max_pool*4 symbols for screening.
    - Test mode honors SCREENER_TEST_MODE_UNIVERSE override when provided.
    - If cache is corrupt/missing, quarantine & trigger a one-shot rebuild, then retry once.
    - Final fallback: DEFAULT_SYMBOLS env (comma/space) or a small safe set.
    """
    test_mode = is_test_mode_active()
    if test_mode:
        override = _parse_test_universe()
        if override:
            return override[: max_pool * 4]

    # Try safe loader first (handles corruption and quarantines .bad)
    symbols_rec = safe_load_universe_cache()
    if symbols_rec is None:
        # Attempt an idempotent rebuild
        try:
            from tbot_bot.screeners.universe_orchestrator import main as rebuild_universe
            log_event("finnhub_screener", "Universe cache invalid — attempting rebuild")
            rebuild_universe()
            symbols_rec = safe_load_universe_cache()
        except Exception as e:
            log_event("finnhub_screener", f"Universe rebuild attempt failed: {e}")

    if symbols_rec:
        return [s["symbol"] for s in symbols_rec][: max_pool * 4]

    # Fallback: use DEFAULT_SYMBOLS or a tiny safe set to keep strategy alive
    fallback_raw = str(config.get("DEFAULT_SYMBOLS", "AAPL MSFT SPY QQQ")).strip()
    fallback = [t.strip().upper() for t in fallback_raw.replace(",", " ").split() if t.strip()]
    log_event("finnhub_screener", f"Using fallback symbol set ({len(fallback)}): {fallback}")
    return fallback[: max_pool * 4]

class FinnhubScreener(ScreenerBase):
    """
    Finnhub screener: loads eligible symbols from universe cache,
    fetches latest quotes from Finnhub API using screener credentials,
    filters using centralized screener_filter. Test-mode aware.
    """
    def __init__(self, *args, strategy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.strategy = strategy

    def fetch_live_quotes(self, symbols):
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
                c = float(data.get("c", 0) or 0)
                o = float(data.get("o", 0) or 0)
                vwap = float(data.get("vwap", 0) or 0)
                c, o, vwap = _normalize_price_fields(c, o, vwap if vwap else (c if c else 0))
                quotes.append({"symbol": symbol, "c": c, "o": o, "vwap": vwap or c})
            except Exception as e:
                log(f"Exception fetching quote for {symbol}: {e}")
                continue
            if idx % 50 == 0 and idx > 0:
                log(f"Fetched {idx} quotes...")
            time.sleep(STRATEGY_SLEEP_TIME)
        return quotes

    def _build_price_candidates(self, quotes):
        try:
            universe_cache = {s["symbol"]: s for s in load_universe_cache()}
        except Exception:
            universe_cache = {}
        candidates = []
        for q in quotes:
            symbol = q["symbol"]
            c, o, vwap = q["c"], q["o"], q["vwap"]
            if c <= 0 or o <= 0 or vwap <= 0:
                continue
            mc = float(universe_cache.get(symbol, {}).get("marketCap", 0) or 0)
            exch = universe_cache.get(symbol, {}).get("exchange", "US")
            frac = bool(universe_cache.get(symbol, {}).get("isFractional", FRACTIONAL))
            candidates.append({
                "symbol": symbol,
                "lastClose": c,
                "marketCap": mc / 1_000_000 if mc else 0,
                "exchange": exch,
                "isFractional": frac,
                "price": c,
                "vwap": vwap,
                "open": o
            })
        return candidates

    def run_screen(self, pool_size=15):
        test_mode = is_test_mode_active()
        # --- CHANGED (surgical): use resilient universe symbol loader
        all_symbols = _get_universe_symbols(pool_size)

        quotes = self.fetch_live_quotes(all_symbols)
        candidates = self._build_price_candidates(quotes)
        if test_mode:
            filtered = core_filter_symbols(candidates, min_price=MIN_PRICE, max_price=MAX_PRICE,
                                           min_market_cap=0, max_market_cap=1e12, max_size=pool_size * 2)
        else:
            filtered = core_filter_symbols(candidates, min_price=MIN_PRICE, max_price=MAX_PRICE,
                                           min_market_cap=float(config.get("MIN_MARKET_CAP", 0) or 0.0),
                                           max_market_cap=float(config.get("MAX_MARKET_CAP", 1e12) or 1e12),
                                           max_size=pool_size * 2)
        results = []
        present = {f["symbol"] for f in filtered}
        for q in candidates:
            if q["symbol"] not in present:
                continue
            momentum = abs(q["price"] - q["open"]) / q["open"] if q["open"] else 0
            results.append({
                "symbol": q["symbol"],
                "price": q["price"],
                "vwap": q["vwap"],
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("finnhub_screener", f"run_screen returned {len(results[:pool_size])} candidates")
        return results[:pool_size]

    def filter_candidates(self, quotes):
        test_mode = is_test_mode_active()
        limit = int(self.env.get("SCREENER_LIMIT", 3))
        candidates = self._build_price_candidates(quotes)
        if test_mode:
            filtered = core_filter_symbols(candidates, min_price=MIN_PRICE, max_price=MAX_PRICE,
                                           min_market_cap=0, max_market_cap=1e12, max_size=limit)
        else:
            filtered = core_filter_symbols(candidates, min_price=MIN_PRICE, max_price=MAX_PRICE,
                                           min_market_cap=float(config.get("MIN_MARKET_CAP", 0) or 0.0),
                                           max_market_cap=float(config.get("MAX_MARKET_CAP", 1e12) or 1e12),
                                           max_size=limit)
        results = []
        present = {f["symbol"] for f in filtered}
        for q in candidates:
            if q["symbol"] not in present:
                continue
            momentum = abs(q["price"] - q["open"]) / q["open"] if q["open"] else 0
            results.append({
                "symbol": q["symbol"],
                "price": q["price"],
                "vwap": q["vwap"],
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("finnhub_screener", f"filter_candidates returned {len(results[:limit])} candidates (legacy mode)")
        return results[:limit]
