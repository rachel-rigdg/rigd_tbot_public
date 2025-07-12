# tbot_bot/screeners/symbol_universe_refresh.py
# PRODUCTION-READY: Delegates all symbol/quote fetching to provider modules. No direct API calls.

import sys
import json
import os
from datetime import datetime, timezone
from typing import List, Dict
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import (
    save_universe_cache, load_blocklist, UniverseCacheError
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

def write_partial(symbols, meta=None):
    partial_path = resolve_universe_partial_path()
    cache_obj = {
        "schema_version": "1.0.0",
        "build_timestamp_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "symbols": symbols
    }
    if meta:
        cache_obj["meta"] = meta
    with open(partial_path, "w", encoding="utf-8") as pf:
        json.dump(cache_obj, pf, indent=2)

def write_unfiltered(unfiltered_symbols):
    with open(UNFILTERED_PATH, "w", encoding="utf-8") as uf:
        json.dump({"symbols": unfiltered_symbols}, uf, indent=2)

def load_unfiltered():
    try:
        with open(UNFILTERED_PATH, "r", encoding="utf-8") as uf:
            data = json.load(uf)
            return data.get("symbols", [])
    except Exception:
        return []

def get_universe_screener_creds():
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
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

def fetch_symbols_with_provider(env):
    screener_secrets = get_universe_screener_creds()
    name = (screener_secrets.get("SCREENER_NAME") or "").strip().upper()
    ProviderClass = get_provider_class(name)
    if ProviderClass is None:
        raise RuntimeError(f"No provider class mapping found for SCREENER_NAME '{name}'")
    merged_config = env.copy()
    merged_config.update(screener_secrets)
    provider = ProviderClass(merged_config, screener_secrets)
    return provider.fetch_symbols()

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

    try:
        symbols_unfiltered = fetch_symbols_with_provider(env)
        if not symbols_unfiltered or len(symbols_unfiltered) < 10:
            raise RuntimeError("No symbols fetched from screener provider; check API key, network, or provider limits.")
        write_unfiltered(symbols_unfiltered)
    except Exception as e:
        log_progress("Failed to fetch screener symbols", {"error": str(e)})
        raise

    log_progress("Fetched symbols from screener provider", {"count": len(symbols_unfiltered)})

    # Write initial unfiltered and deduped symbols (pre-enrichment)
    try:
        write_partial(dedupe_symbols(symbols_unfiltered))
    except Exception as e:
        log_progress("Write partial failed", {"error": str(e)})

    try:
        save_universe_cache(dedupe_symbols(symbols_unfiltered), bot_identity=bot_identity)
        log_progress("Universe cache build complete", {"final_count": len(symbols_unfiltered)})
    except Exception as e:
        log_progress("Failed to write universe cache", {"error": str(e)})
        raise

    # No enrichment or filtering done here; handled only in symbol_enrichment.py

    audit = {
        "build_time_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "total_symbols_fetched": len(symbols_unfiltered),
        "total_symbols_final": len(symbols_unfiltered),
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
