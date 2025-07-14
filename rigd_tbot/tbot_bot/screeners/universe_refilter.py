# tbot_bot/screeners/universe_refilter.py

import os
import sys
import json
from tbot_bot.screeners.screener_utils import atomic_copy_file
from tbot_bot.screeners.screener_filter import normalize_symbols, passes_filter
from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path, resolve_universe_cache_path, resolve_universe_unfiltered_path
)
from tbot_bot.config.env_bot import load_env_bot_config

PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
UNFILTERED_PATH = resolve_universe_unfiltered_path()

def main():
    env = load_env_bot_config()
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

    if not os.path.exists(UNFILTERED_PATH):
        print(f"Missing: {UNFILTERED_PATH}")
        sys.exit(1)

    syms = []
    with open(UNFILTERED_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                syms.append(json.loads(line))
            except Exception:
                continue

    filtered = []
    for s in normalize_symbols(syms):
        passed, _ = passes_filter(
            s,
            min_price,
            max_price,
            min_cap,
            max_cap
        )
        if passed:
            filtered.append(s)
        if max_size and len(filtered) >= max_size:
            break

    with open(PARTIAL_PATH, "w", encoding="utf-8") as f:
        for s in filtered:
            f.write(json.dumps(s) + "\n")
    atomic_copy_file(PARTIAL_PATH, FINAL_PATH)
    print(f"Filtered {len(filtered)} symbols to {PARTIAL_PATH}")

if __name__ == "__main__":
    main()
