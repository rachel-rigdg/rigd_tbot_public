# tbot_bot/screeners/screeners/ibkr_screener.py
# Loads screener credentials where TRADING_ENABLED == "true" and PROVIDER == "IBKR" per central flag.
# Only enabled providers are used for IBKR screener operation.

import time
from tbot_bot.screeners.screener_base import ScreenerBase
from tbot_bot.screeners.screener_filter import filter_symbols as core_filter_symbols
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.screeners.screener_utils import load_universe_cache
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.utils_log import log_event

def get_trading_screener_creds():
    # Only use providers with TRADING_ENABLED == "true" and PROVIDER == "IBKR"
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"TRADING_ENABLED_{k.split('_')[-1]}", "false").upper() == "TRUE"
           and all_creds.get(k, "").strip().upper() == "IBKR"
    ]
    if not provider_indices:
        raise RuntimeError("No IBKR screener providers enabled for active trading. Please enable at least one in the credential admin.")
    idx = provider_indices[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

config = get_bot_config()
screener_creds = get_trading_screener_creds()
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)

def log(msg):
    if LOG_LEVEL == "verbose":
        print(f"[IBKR Screener] {msg}")

class IBKRScreener(ScreenerBase):
    """
    IBKR screener: loads eligible symbols from universe cache,
    fetches latest quotes from IBKR (using screener credentials), filters per strategy.
    Ensures output always flags is_fractional eligibility.
    """
    def __init__(self, strategy=None, **kwargs):
        super().__init__()
        self.strategy = strategy

    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using IBKR API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        # Replace this placeholder logic with a real IBKR API fetch using only screener_creds.
        # Real logic should use an injected provider module with screener_creds.
        quotes = []
        for idx, symbol in enumerate(symbols):
            try:
                # --- BEGIN PLACEHOLDER ---
                import random
                c = round(random.uniform(10, 200), 2)
                o = round(c * random.uniform(0.97, 1.03), 2)
                vwap = (c + o) / 2
                quote = {"symbol": symbol, "c": c, "o": o, "vwap": vwap}
                # --- END PLACEHOLDER ---
                if quote and all(k in quote for k in ("c", "o", "vwap")):
                    quotes.append(quote)
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
        strategy = self.env.get("STRATEGY_NAME", "open")
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
            price_candidates.append({
                "symbol": symbol,
                "lastClose": current,
                "marketCap": mc,
                "exchange": exch,
                "isFractional": is_fractional, # isFractional is informational only; not used for screening—checked in order logic.
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
            max_size=pool_size * 2
        )

        results = []
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
            momentum = abs(current - open_) / open_
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("ibkr_screener", f"run_screen returned {len(results[:pool_size])} candidates")
        return results[:pool_size]

    def filter_candidates(self, quotes):
        """
        DEPRECATED: Returns a filtered, sorted candidate list for legacy modules.
        """
        strategy = self.env.get("STRATEGY_NAME", "open")
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
            gap = abs((current - open_) / open_) if open_ else 0
            if gap > max_gap:
                continue
            momentum = abs(current - open_) / open_
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("ibkr_screener", f"filter_candidates returned {len(results)} candidates (legacy mode)")
        return results
