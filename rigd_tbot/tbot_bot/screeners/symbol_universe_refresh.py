# tbot_bot/screeners/symbol_universe_refresh.py
# Nightly job to build, filter, and atomically write the symbol universe cache for all screeners
# Fully aligned with RIGD TradeBot screener/cache specification

import sys
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict

from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import (
    save_universe_cache, filter_symbols, load_blocklist, UniverseCacheError
)
from tbot_bot.support.path_resolver import resolve_universe_cache_path

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
LOG = logging.getLogger("symbol_universe_refresh")

def fetch_broker_symbol_metadata() -> List[Dict]:
    """
    Fetches all US symbols/metadata from the configured provider in .env_bot (SCREENER_SOURCE).
    Returns a list of dicts: symbol, exchange, lastClose, marketCap, name, sector, industry, volume.
    """
    env = load_env_bot_config()
    screener_source = env.get("SCREENER_SOURCE", "FINNHUB").strip().upper()
    if screener_source == "FINNHUB":
        return fetch_finnhub_symbols(env)
    elif screener_source == "ALPACA":
        return fetch_alpaca_symbols(env)
    elif screener_source == "TRADIER":
        return fetch_tradier_symbols(env)
    elif screener_source == "IBKR":
        return fetch_ibkr_symbols(env)
    else:
        raise RuntimeError(f"Unsupported SCREENER_SOURCE: {screener_source}")

def fetch_finnhub_symbols(env):
    import requests
    FINNHUB_API_KEY = env.get("FINNHUB_API_KEY") or env.get("FINNHUB_TOKEN") or env.get("FINNHUB_TOKEN", "")
    if not FINNHUB_API_KEY:
        raise RuntimeError("FINNHUB_API_KEY not set in config")
    symbols = []
    for exch in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(","):
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange={exch.strip()}&token={FINNHUB_API_KEY}"
        r = requests.get(url)
        if r.status_code != 200:
            continue
        for s in r.json():
            symbol = s.get("symbol")
            # Profile lookup for market cap, sector, etc.
            profile_url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}"
            profile = requests.get(profile_url)
            p = profile.json() if profile.status_code == 200 else {}
            # Quote for price/volume
            quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            quote = requests.get(quote_url)
            q = quote.json() if quote.status_code == 200 else {}
            # Compose result
            symbols.append({
                "symbol": symbol,
                "exchange": exch.strip(),
                "lastClose": q.get("pc") or q.get("c"),
                "marketCap": p.get("marketCapitalization"),
                "name": p.get("name") or s.get("description") or "",
                "sector": p.get("finnhubIndustry") or "",
                "industry": "",
                "volume": q.get("v") or 0
            })
    return symbols

def fetch_alpaca_symbols(env):
    import requests
    api_key = env.get("ALPACA_API_KEY", "")
    secret_key = env.get("ALPACA_SECRET_KEY", "")
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    }
    url = "https://paper-api.alpaca.markets/v2/assets?status=active&asset_class=us_equity"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError("Failed to fetch symbols from Alpaca")
    data = r.json()
    results = []
    for s in data:
        symbol = s["symbol"]
        exch = s.get("exchange", "")
        # Market cap and sector not available directly
        # Optionally, fetch from a secondary API/source if needed
        results.append({
            "symbol": symbol,
            "exchange": exch,
            "lastClose": s.get("last_close", 0),
            "marketCap": None,
            "name": s.get("name") or "",
            "sector": "",
            "industry": "",
            "volume": 0
        })
    return results

def fetch_tradier_symbols(env):
    import requests
    api_key = env.get("TRADIER_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    url = "https://api.tradier.com/v1/markets/symbols"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError("Failed to fetch symbols from Tradier")
    data = r.json().get("symbols", {}).get("symbol", [])
    results = []
    for s in data:
        results.append({
            "symbol": s.get("symbol", ""),
            "exchange": s.get("exchange", ""),
            "lastClose": None,
            "marketCap": None,
            "name": s.get("description", ""),
            "sector": "",
            "industry": "",
            "volume": 0
        })
    return results

def fetch_ibkr_symbols(env):
    # Implement per your IBKR integration; stubbed here
    # IBKR does not provide a public full US equity list via web API
    return []

def main():
    # 1. Load config
    env = load_env_bot_config()
    exchanges = [e.strip() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 5))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 100))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 2_000_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))
    blocklist_path = env.get("SCREENER_UNIVERSE_BLOCKLIST_PATH", None)
    bot_identity = env.get("BOT_IDENTITY_STRING", None)

    LOG.info(f"Universe build parameters: exchanges={exchanges}, price=[{min_price},{max_price}), cap=[{min_cap},{max_cap}], max_size={max_size}, blocklist={blocklist_path}")

    # 2. Load broker symbols (should fetch all possible for the session)
    LOG.info("Fetching symbol metadata from broker API(s)...")
    try:
        symbols_raw = fetch_broker_symbol_metadata()
        if not symbols_raw or len(symbols_raw) < 10:
            raise RuntimeError("No symbols fetched from broker/API; check API key, network, or provider limits.")
    except Exception as e:
        LOG.error(f"Failed to fetch broker symbol metadata: {e}")
        raise

    LOG.info(f"Fetched {len(symbols_raw)} raw symbols from broker feed.")

    # 3. Load manual blocklist
    blocklist = load_blocklist(blocklist_path)

    # 4. Filter by exchange, price, cap, blocklist, and max size
    symbols_filtered = filter_symbols(
        symbols=symbols_raw,
        exchanges=exchanges,
        min_price=min_price,
        max_price=max_price,
        min_market_cap=min_cap,
        max_market_cap=max_cap,
        blocklist=blocklist,
        max_size=max_size
    )

    # 5. Prepare JSON for cache (sorted by symbol for consistency)
    symbols_filtered.sort(key=lambda x: x["symbol"])

    # 6. Save universe cache atomically
    try:
        save_universe_cache(symbols_filtered, bot_identity=bot_identity)
        LOG.info(f"Universe cache build complete: {len(symbols_filtered)} symbols written.")
    except Exception as e:
        LOG.error(f"Failed to write universe cache: {e}")
        raise

    # 7. Health/Audit Summary
    audit = {
        "build_time_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "total_symbols_fetched": len(symbols_raw),
        "total_symbols_final": len(symbols_filtered),
        "exchanges": exchanges,
        "blocklist_entries": len(blocklist),
        "cache_path": resolve_universe_cache_path(bot_identity),
    }
    LOG.info("Universe build summary: " + json.dumps(audit, indent=2))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        LOG.error(f"Universe build failed and raised exception: {e}")
        sys.exit(1)
