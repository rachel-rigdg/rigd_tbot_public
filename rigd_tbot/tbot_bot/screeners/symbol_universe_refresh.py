# tbot_bot/screeners/symbol_universe_refresh.py
# PRODUCTION-READY: Implements batchwise universe build with atomic batch writes and filtering, using yfinance for symbol/quote fetching.

import sys
import json
import os
from datetime import datetime, timezone
from typing import List, Dict
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import (
    save_universe_cache, load_blocklist, UniverseCacheError, filter_symbols
)
from tbot_bot.screeners.screener_filter import dedupe_symbols
from tbot_bot.support.path_resolver import (
    resolve_universe_cache_path,
    resolve_universe_partial_path,
    resolve_universe_log_path,
    resolve_screener_blocklist_path
)
from tbot_bot.support.secrets_manager import (
    get_screener_credentials_path,
    load_screener_credentials
)
from tbot_bot.screeners.provider_registry import get_provider_class

UNFILTERED_PATH = "tbot_bot/output/screeners/symbol_universe.unfiltered.json"
PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
LOG_PATH = resolve_universe_log_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()

def screener_creds_exist():
    creds_path = get_screener_credentials_path()
    return os.path.exists(creds_path)

def log_progress(msg: str, details: dict = None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")

def atomic_write_json(path, obj):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp_path, path)

def main():
    if not screener_creds_exist():
        print("Screener credentials not configured. Please configure screener credentials in the UI before building the universe.")
        sys.exit(2)
    env = load_env_bot_config()
    exchanges = [e.strip() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 2_000_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))
    batch_size = 100
    blocklist_path = BLOCKLIST_PATH
    bot_identity = env.get("BOT_IDENTITY_STRING", None)

    log_progress("Universe build parameters", {
        "exchanges": exchanges,
        "price": [min_price, max_price],
        "cap": [min_cap, max_cap],
        "max_size": max_size,
        "blocklist": blocklist_path
    })

    try:
        with open(blocklist_path, "r", encoding="utf-8") as bf:
            blocklist = [b.strip() for b in bf.readlines() if b.strip()]
    except Exception:
        blocklist = []

    # Fetch provider and iterate in batches
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"UNIVERSE_ENABLED_{k.split('_')[-1]}", "false").lower() == "true"
    ]
    if not provider_indices:
        raise RuntimeError("No screener providers enabled for universe build. Please enable at least one in the credential admin.")
    idx = provider_indices[0]
    screener_secrets = {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }
    name = (screener_secrets.get("SCREENER_NAME") or "").strip().upper()
    ProviderClass = get_provider_class(name)
    if ProviderClass is None:
        raise RuntimeError(f"No provider class mapping found for SCREENER_NAME '{name}'")
    merged_config = env.copy()
    merged_config.update(screener_secrets)
    provider = ProviderClass(merged_config)

    symbols_unfiltered = []
    partial_symbols = []
    count = 0

    # Build in batches, writing after each batch
    syms = provider.fetch_symbols()
    total = len(syms)
    log_progress("Fetched all symbols from provider", {"total_symbols": total})

    for i in range(0, total, batch_size):
        batch = syms[i:i + batch_size]
        count += len(batch)
        # Append raw to unfiltered
        symbols_unfiltered.extend(batch)
        atomic_write_json(UNFILTERED_PATH, {"symbols": symbols_unfiltered})
        # Filter batch and append to partial
        filtered = filter_symbols(
            symbols=batch,
            exchanges=exchanges,
            min_price=min_price,
            max_price=max_price,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            blocklist=blocklist,
            max_size=max_size
        )
        partial_symbols.extend(filtered)
        atomic_write_json(PARTIAL_PATH, {
            "schema_version": "1.0.0",
            "build_timestamp_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "symbols": partial_symbols
        })
        log_progress("Batch processed", {
            "batch_start": i + 1,
            "batch_end": i + len(batch),
            "unfiltered_count": len(symbols_unfiltered),
            "partial_count": len(partial_symbols)
        })

    # After all batches, copy partial to final
    atomic_write_json(FINAL_PATH, dedupe_symbols(partial_symbols))
    save_universe_cache(dedupe_symbols(partial_symbols), bot_identity=bot_identity)
    log_progress("Universe cache build complete", {"final_count": len(partial_symbols)})

    audit = {
        "build_time_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "total_symbols_fetched": len(symbols_unfiltered),
        "total_symbols_final": len(partial_symbols),
        "exchanges": exchanges,
        "blocklist_entries": len(blocklist),
        "cache_path": resolve_universe_cache_path(bot_identity),
    }
    log_progress("Universe build summary", audit)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Universe build failed and raised exception", {"error": str(e)})
        sys.exit(1)
