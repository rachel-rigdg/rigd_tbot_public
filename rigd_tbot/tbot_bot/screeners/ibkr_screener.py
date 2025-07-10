# tbot_bot/screeners/ibkr_screener.py
# UPDATE: Loads screener credentials where TRADING_ENABLED == "true" per central flag.
# Only enabled providers are used for IBKR screener operation.

import time
from tbot_bot.screeners.screener_base import ScreenerBase
from tbot_bot.screeners.screener_filter import filter_symbols as core_filter_symbols
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.screeners.screener_utils import load_universe_cache
from tbot_bot.support.secrets_manager import load_screener_credentials

# Placeholder: replace with real IBKR API imports and logic as needed
def ibkr_get_quote(symbol):
    """
    Replace this stub with real IBKR market data API call.
    Return dict: {"symbol":..., "c":..., "o":..., "vwap":...}
    """
    # Example (mock): simulate current, open, vwap
    import random
    c = round(random.uniform(10, 200), 2)
    o = round(c * random.uniform(0.97, 1.03), 2)
    vwap = (c + o) / 2
    return {"symbol": symbol, "c": c, "o": o, "vwap": vwap}

def get_trading_screener_creds():
    # Only use providers with TRADING_ENABLED == "true"
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"TRADING_ENABLED_{k.split('_')[-1]}", "false") == "true"
    ]
    if not provider_indices:
        raise RuntimeError("No screener providers enabled for active trading. Please enable at least one in the credential admin.")
    idx = provider_indices[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

config = get_bot_config()
broker_creds = get_trading_screener_creds()
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)

def log(msg):
    if LOG_LEVEL == "verbose":
        print(msg)

class IBKRScreener(ScreenerBase):
    """
    IBKR screener: loads eligible symbols from universe cache,
    fetches latest quotes from IBKR, filters per strategy.
    """
    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using IBKR API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        for idx, symbol in enumerate(symbols):
            try:
                quote = ibkr_get_quote(symbol)
                if quote and all(k in quote for k in ("c", "o", "vwap")):
                    quotes.append(quote)
            except Exception as e:
                log(f"Exception fetching quote for {symbol}: {e}")
                continue
            if idx % 50 == 0:
                log(f"Fetched {idx} quotes...")
            time.sleep(0.2)  # Throttle if needed
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
