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

# --- Mock or Import Broker Symbol Loader Here ---
def fetch_broker_symbol_metadata() -> List[Dict]:
    """
    Replace this stub with a unified broker API call that returns all US symbols and metadata:
    Each dict must include: symbol, exchange, lastClose, marketCap, name, sector, industry, volume.
    """
    # Placeholder example
    return [
        {"symbol": "AAPL", "exchange": "NASDAQ", "lastClose": 190.5, "marketCap": 2900000000000, "name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "volume": 1000000},
        {"symbol": "IBM", "exchange": "NYSE", "lastClose": 160.3, "marketCap": 145000000000, "name": "IBM Corp", "sector": "Technology", "industry": "Information Tech", "volume": 500000},
        # ... Add all fetched symbols
    ]

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
    except Exception as e:
        LOG.error(f"Failed to fetch broker symbol metadata: {e}")
        sys.exit(1)

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
        sys.exit(2)

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
    main()
