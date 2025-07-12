# tbot_bot/screeners/symbol_universe_refresh.py
# Implements atomic, staged universe build: reads symbol source, enriches and writes to unfiltered.json per symbol, filters to partial.json, blocklists rejects, and finalizes to symbol_universe.json.

import sys
import json
import os
import time
from datetime import datetime, timezone
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import (
    atomic_append_json, atomic_append_text, load_blocklist, dedupe_symbols
)
from tbot_bot.screeners.screener_filter import normalize_symbols, passes_filter
from tbot_bot.support.path_resolver import (
    resolve_universe_unfiltered_path,
    resolve_universe_partial_path,
    resolve_universe_cache_path,
    resolve_universe_log_path,
    resolve_screener_blocklist_path
)
from tbot_bot.support.secrets_manager import (
    get_screener_credentials_path,
    load_screener_credentials
)
from tbot_bot.screeners.provider_registry import get_provider_class

UNFILTERED_PATH = resolve_universe_unfiltered_path()
PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
LOG_PATH = resolve_universe_log_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()

def screener_creds_exist():
    creds_path = get_screener_credentials_path()
    return os.path.exists(creds_path)

def log_progress(msg, details=None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")

def main():
    if not screener_creds_exist():
        print("Screener credentials not configured. Please configure screener credentials in the UI before building the universe.")
        sys.exit(2)
    env = load_env_bot_config()
    exchanges = [e.strip().upper() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NASDAQ,NYSE").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 2_000_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))
    batch_size = 100
    blocklist_path = BLOCKLIST_PATH
    bot_identity = env.get("BOT_IDENTITY_STRING", None)
    sleep_time = float(env.get("UNIVERSE_SLEEP_TIME", 2.0))

    log_progress("Universe build parameters", {
        "exchanges": exchanges,
        "price": [min_price, max_price],
        "cap": [min_cap, max_cap],
        "max_size": max_size,
        "blocklist": blocklist_path
    })

    try:
        blocklist = set(load_blocklist(blocklist_path))
    except Exception:
        blocklist = set()

    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"UNIVERSE_ENABLED_{k.split('_')[-1]}", "false").upper() == "TRUE"
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

    syms = provider.fetch_symbols()
    total = len(syms)
    log_progress("Fetched all symbols from provider", {"total_symbols": total})

    enriched_count = 0
    blocklisted_count = 0

    for i in range(0, total, batch_size):
        batch_syms = syms[i:i + batch_size]
        batch_norm = normalize_symbols(batch_syms)
        for sym_obj in batch_norm:
            sym = sym_obj.get("symbol")
            if not sym or sym in blocklist:
                continue
            atomic_append_json(UNFILTERED_PATH, sym_obj)
            filter_result, reason = passes_filter(sym_obj, exchanges, min_price, max_price, min_cap, max_cap)
            if filter_result:
                atomic_append_json(PARTIAL_PATH, sym_obj)
                enriched_count += 1
            else:
                atomic_append_text(BLOCKLIST_PATH, f"{sym}|{reason}|{datetime.utcnow().isoformat()}Z\n")
                blocklisted_count += 1
            if enriched_count >= max_size:
                break
        log_progress("Batch processed", {
            "batch_start": i + 1,
            "batch_end": i + len(batch_syms),
            "unfiltered_count": enriched_count + blocklisted_count,
            "partial_count": enriched_count
        })
        if enriched_count >= max_size:
            break
        time.sleep(sleep_time)

    # Finalize: copy partial.json to final universe
    try:
        with open(PARTIAL_PATH, "r", encoding="utf-8") as pf:
            partial_data = json.load(pf)
        with open(FINAL_PATH, "w", encoding="utf-8") as ff:
            json.dump(partial_data, ff, indent=2)
    except Exception as e:
        log_progress("Failed to finalize universe", {"error": str(e)})
        print(f"ERROR: Finalization failed: {e}", flush=True)
        sys.exit(1)

    log_progress("Universe cache build complete", {"final_count": enriched_count})

    audit = {
        "build_time_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "total_symbols_fetched": total,
        "total_symbols_final": enriched_count,
        "exchanges": exchanges,
        "blocklist_entries": len(blocklist),
        "cache_path": FINAL_PATH,
    }
    log_progress("Universe build summary", audit)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Universe build failed and raised exception", {"error": str(e)})
        sys.exit(1)
