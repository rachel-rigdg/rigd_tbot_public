# tbot_bot/screeners/universe_refilter.py
# CLI: python3 -m tbot_bot.screeners.universe_refilter

import os
import json
from tbot_bot.screeners.screener_filter import normalize_symbols, filter_symbols
from tbot_bot.support.path_resolver import (
    resolve_universe_unfiltered_path, resolve_universe_partial_path, resolve_universe_cache_path
)
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import atomic_copy_file, atomic_append_json

UNFILTERED_PATH = resolve_universe_unfiltered_path()
PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()

def main():
    env = load_env_bot_config()
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

    # Read all unfiltered symbols
    syms = []
    with open(UNFILTERED_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                syms.append(json.loads(line))
            except Exception:
                continue

    # Apply filtering (blocklist ignored here)
    filtered = filter_symbols(
        syms,
        min_price,
        max_price,
        min_cap,
        max_cap,
        blocklist=None,
        max_size=max_size
    )

    # Overwrite partial and final with filtered
    with open(PARTIAL_PATH, "w", encoding="utf-8") as pf:
        for rec in filtered:
            pf.write(json.dumps(rec) + "\n")
    atomic_copy_file(PARTIAL_PATH, FINAL_PATH)
    print(f"Filtered {len(filtered)} symbols to {PARTIAL_PATH} and {FINAL_PATH}")

if __name__ == "__main__":
    main()
