# tbot_bot/screeners/symbol_enrichment.py
# Stage 2: Enriches symbols in symbol_universe.unfiltered.json with price, market cap, and volume via active enrichment provider (e.g. Finnhub).
# - Blocklists any symbol with missing/invalid data or price below min_price.
# - Writes enriched symbols to symbol_universe.partial.json and symbol_universe.json (final).
# - 100% compliant with modular provider, blocklist, and storage architecture.

import os
import sys
import json
import time
from datetime import datetime, timezone
from tbot_bot.screeners.screener_utils import (
    load_unfiltered_cache, save_universe_cache, dedupe_symbols, load_blocklist
)
from tbot_bot.screeners.screener_filter import normalize_symbols
from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path, resolve_universe_cache_path, resolve_screener_blocklist_path, resolve_universe_log_path
)
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.provider_registry import get_provider_class

PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()
LOG_PATH = resolve_universe_log_path()

def log_progress(msg, details=None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")

def get_enrichment_provider_creds():
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"UNIVERSE_ENABLED_{k.split('_')[-1]}", "false").upper() == "TRUE"
           and not all_creds.get(f"SCREENER_NAME_{k.split('_')[-1]}", "").upper().endswith("_TXT")
    ]
    if not provider_indices:
        raise RuntimeError("No valid enrichment provider enabled for universe build. Enable a data API provider (not *_TXT) in the credential admin.")
    idx = provider_indices[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

def write_partial(symbols, meta=None):
    cache_obj = {
        "schema_version": "1.0.0",
        "build_timestamp_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "symbols": symbols
    }
    if meta:
        cache_obj["meta"] = meta
    with open(PARTIAL_PATH, "w", encoding="utf-8") as pf:
        json.dump(cache_obj, pf, indent=2)

def append_blocklist(new_block_syms):
    if not new_block_syms:
        return
    blk_syms = set(load_blocklist(BLOCKLIST_PATH))
    new_syms = [s for s in new_block_syms if s not in blk_syms]
    if new_syms:
        with open(BLOCKLIST_PATH, "a", encoding="utf-8") as blf:
            for sym in new_syms:
                blf.write(f"{sym}\n")

def main():
    env = load_env_bot_config()
    sleep_time = float(env.get("UNIVERSE_SLEEP_TIME", 0.5))
    unfiltered = load_unfiltered_cache()
    if not unfiltered or len(unfiltered) < 10:
        log_progress("No symbols to enrich (unfiltered cache empty or missing).")
        sys.exit(1)

    exchanges = [e.strip().upper() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

    blocklist = set(load_blocklist(BLOCKLIST_PATH))
    bot_identity = env.get("BOT_IDENTITY_STRING", None)
    try:
        screener_secrets = get_enrichment_provider_creds()
    except Exception as e:
        log_progress("No valid enrichment provider enabled. Aborting enrichment.", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(2)
    name = (screener_secrets.get("SCREENER_NAME") or "").strip().upper()
    if name.endswith("_TXT"):
        log_progress("TXT provider selected as enrichment provider, aborting enrichment.", {"provider": name})
        print(f"ERROR: TXT providers (like {name}) cannot be used for enrichment. Enable a data API provider (e.g. Finnhub, Polygon).", flush=True)
        sys.exit(2)
    ProviderClass = get_provider_class(name)
    if ProviderClass is None:
        raise RuntimeError(f"No provider class mapping found for SCREENER_NAME '{name}'")
    merged_config = env.copy()
    merged_config.update(screener_secrets)
    provider = ProviderClass(merged_config)

    symbols = [s for s in normalize_symbols(unfiltered) if s.get("symbol") not in blocklist]
    all_symbols = [s["symbol"] for s in symbols if "symbol" in s]
    enriched = []
    new_blocked = set()

    BATCH_SIZE = 100
    total_batches = (len(all_symbols) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(all_symbols), BATCH_SIZE):
        batch = all_symbols[i:i+BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        print(f"[symbol_enrichment] Processing batch {batch_num} of {total_batches}, symbols {i+1}-{i+len(batch)}", flush=True)
        log_progress("Processing batch", {"batch_num": batch_num, "of": total_batches, "start_idx": i+1, "end_idx": i+len(batch)})
        try:
            quotes = provider.fetch_quotes(batch)
        except Exception as e:
            log_progress("Failed to fetch quotes for batch", {"error": str(e), "batch": batch})
            print(f"[symbol_enrichment] Batch {batch_num} failed: {e}", flush=True)
            for sym in batch:
                new_blocked.add(sym)
            continue
        quote_map = {q["symbol"]: q for q in quotes if "symbol" in q}
        for s in symbols[i:i+BATCH_SIZE]:
            sym = s["symbol"]
            q = quote_map.get(sym)
            if not q:
                new_blocked.add(sym)
                continue
            price = q.get("c") or q.get("close") or q.get("lastClose") or q.get("price")
            cap = q.get("marketCap") or q.get("market_cap")
            volume = q.get("v") or q.get("volume")
            try:
                price = float(price)
                cap = float(cap) if cap is not None else None
            except Exception:
                new_blocked.add(sym)
                continue
            if price is None or price < min_price or price > max_price or (cap is not None and (cap < min_cap or cap > max_cap)):
                new_blocked.add(sym)
                continue
            record = dict(s)
            record["lastClose"] = price
            if cap is not None:
                record["marketCap"] = cap
            if volume is not None:
                record["volume"] = volume
            for k in q:
                if k not in record:
                    record[k] = q[k]
            enriched.append(record)
            if len(enriched) >= max_size:
                break
        print(f"[symbol_enrichment] Batch {batch_num} complete. Total enriched so far: {len(enriched)}", flush=True)
        if len(enriched) >= max_size:
            print(f"[symbol_enrichment] Reached max universe size {max_size}, stopping enrichment.", flush=True)
            break
        time.sleep(sleep_time)

    write_partial(dedupe_symbols(enriched))
    save_universe_cache(dedupe_symbols(enriched), bot_identity=bot_identity)
    append_blocklist(new_blocked)
    log_progress("Enrichment complete", {
        "enriched_count": len(enriched),
        "blocklisted": len(new_blocked),
        "final_path": FINAL_PATH
    })

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Enrichment failed and raised exception", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
