# tbot_bot/screeners/tradier_screener.py
# UPDATE: Loads screener credentials where TRADING_ENABLED == "true" per central flag.
# Only enabled providers are used for Tradier screener operation.

import requests
import time
from tbot_bot.screeners.screener_base import ScreenerBase
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.secrets_manager import load_screener_credentials

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
tradier_creds = get_trading_screener_creds()
TRADIER_API_KEY = tradier_creds.get("BROKER_API_KEY", "")
BASE_URL = "https://api.tradier.com/v1/markets"
HEADERS = {
    "Authorization": f"Bearer {TRADIER_API_KEY}",
    "Accept": "application/json",
}
API_TIMEOUT = int(config.get("API_TIMEOUT", 30))
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))
FRACTIONAL = config.get("FRACTIONAL", True)
LOG_LEVEL = str(config.get("LOG_LEVEL", "silent")).lower()

def log(msg):
    if LOG_LEVEL == "verbose":
        print(msg)

class TradierScreener(ScreenerBase):
    """
    Tradier screener: loads eligible symbols from universe cache,
    fetches latest quotes from Tradier, filters per strategy.
    """
    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using Tradier API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        # Tradier supports batch quote requests, up to 100 symbols per call
        BATCH_SIZE = 100
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i+BATCH_SIZE]
            symbols_str = ",".join(batch)
            url = f"{BASE_URL}/quotes"
            params = {"symbols": symbols_str}
            try:
                resp = requests.get(url, headers=HEADERS, params=params, timeout=API_TIMEOUT)
                if resp.status_code != 200:
                    log(f"Error fetching batch quotes: status {resp.status_code}")
                    continue
                data = resp.json().get("quotes", {}).get("quote", [])
                # Tradier returns dict if single symbol, list if multiple
                if isinstance(data, dict):
                    data = [data]
                for quote in data:
                    try:
                        symbol = quote.get("symbol")
                        last = float(quote.get("last", 0))
                        open_ = float(quote.get("open", 0))
                        # Tradier does not provide VWAP directly; calculate simple VWAP if possible
                        high = float(quote.get("high", 0))
                        low = float(quote.get("low", 0))
                        vwap = (high + low + last) / 3 if high and low and last else last
                        quotes.append({
                            "symbol": symbol,
                            "c": last,
                            "o": open_,
                            "vwap": vwap
                        })
                    except Exception:
                        continue
            except Exception as e:
                log(f"Exception fetching batch quotes: {e}")
                continue
            time.sleep(0.5)  # Throttle to avoid rate limits
        return quotes

    def filter_candidates(self, quotes):
        """
        Filters the list of quote dicts using price, gap, and other rules.
        Returns eligible symbol dicts.
        """
        # Strategy-specific filter params
        strategy = self.env.get("STRATEGY_NAME", "open")
        gap_key = f"MAX_GAP_PCT_{strategy.upper()}"
        max_gap = float(self.env.get(gap_key, 0.1))

        results = []
        for q in quotes:
            symbol = q["symbol"]
            current = float(q.get("c", 0))
            open_ = float(q.get("o", 0))
            vwap = float(q.get("vwap", 0))

            if current <= 0 or open_ <= 0 or vwap <= 0:
                continue
            if current < MIN_PRICE:
                continue
            if current > MAX_PRICE and not FRACTIONAL:
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
        # Sort by momentum, descending
        results.sort(key=lambda x: x["momentum"], reverse=True)
        return results

# Usage example:
# screener = TradierScreener()
# candidates = screener.run_screen()
