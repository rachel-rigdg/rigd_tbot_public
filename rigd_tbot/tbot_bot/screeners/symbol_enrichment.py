# tbot_bot/screeners/symbol_enrichment.py
# Stage 2: Reads symbols from nasdaqlisted.txt, enriches each symbol using appropriate provider and API, and atomically appends enriched dict to symbol_universe.unfiltered.json.
# Applies batch filter, blocklists failures, appends passing symbols to partial.json, blocklisted to screener_blocklist.txt. No in-memory global state.

import os
import sys
import json
import time
from datetime import datetime, timezone
from tbot_bot.screeners.screener_utils import (
    atomic_append_json, load_unfiltered_cache, dedupe_symbols, load_blocklist, atomic_append_text
)
from tbot_bot.screeners.screener_filter import normalize_symbols, passes_filter
from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path, resolve_universe_cache_path, resolve_screener_blocklist_path, resolve_universe_log_path, resolve_universe_unfiltered_path
)
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.provider_registry import get_provider_class

PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()
LOG_PATH = resolve_universe_log_path()
UNFILTERED_PATH = resolve_universe_unfiltered_path()

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

def main():
    env = load_env_bot_config()
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
    print("DEBUG_CREDENTIALS:", json.dumps(merged_config, indent=2))  # <<<<<< DEBUG LINE
    provider = ProviderClass(merged_config)

    unfiltered = load_unfiltered_cache()
    if not unfiltered or len(unfiltered) < 1:
        log_progress("No symbols to enrich (unfiltered cache empty or missing).")
        sys.exit(1)
    exchanges = [e.strip().upper() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NASDAQ,NYSE").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

    blocklist = set(load_blocklist(BLOCKLIST_PATH))
    all_symbols = [s for s in normalize_symbols(unfiltered) if s.get("symbol") not in blocklist]
    symbol_ids = [s["symbol"] for s in all_symbols if "symbol" in s]
    enriched_count = 0
    blocklisted_count = 0

    BATCH_SIZE = 1
    total_batches = (len(symbol_ids) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(symbol_ids), BATCH_SIZE):
        batch_syms = symbol_ids[i:i+BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        print(f"[symbol_enrichment] Processing batch {batch_num} of {total_batches}, symbols {i+1}-{i+len(batch_syms)}", flush=True)
        log_progress("Processing batch", {"batch_num": batch_num, "of": total_batches, "start_idx": i+1, "end_idx": i+len(batch_syms)})
        try:
            quotes = provider.fetch_quotes(batch_syms)
        except Exception as e:
            log_progress("Failed to fetch quotes for batch", {"error": str(e), "batch": batch_syms})
            print(f"[symbol_enrichment] Batch {batch_num} failed: {e}", flush=True)
            for sym in batch_syms:
                atomic_append_text(BLOCKLIST_PATH, f"{sym}|fetch_failed|{datetime.utcnow().isoformat()}Z\n")
                blocklisted_count += 1
            continue
        quote_map = {q["symbol"]: q for q in quotes if "symbol" in q}
        for s in all_symbols[i:i+BATCH_SIZE]:
            sym = s["symbol"]
            q = quote_map.get(sym)
            if not q:
                atomic_append_text(BLOCKLIST_PATH, f"{sym}|no_quote|{datetime.utcnow().isoformat()}Z\n")
                blocklisted_count += 1
                continue
            price = q.get("c") or q.get("close") or q.get("lastClose") or q.get("price")
            cap = q.get("marketCap") or q.get("market_cap")
            volume = q.get("v") or q.get("volume")
            try:
                price = float(price)
                cap = float(cap) if cap is not None else None
            except Exception:
                atomic_append_text(BLOCKLIST_PATH, f"{sym}|invalid_fields|{datetime.utcnow().isoformat()}Z\n")
                blocklisted_count += 1
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
            atomic_append_json(UNFILTERED_PATH, record)
            filter_result, reason = passes_filter(record, exchanges, min_price, max_price, min_cap, max_cap)
            if filter_result:
                atomic_append_json(PARTIAL_PATH, record)
                enriched_count += 1
            else:
                atomic_append_text(BLOCKLIST_PATH, f"{sym}|{reason}|{datetime.utcnow().isoformat()}Z\n")
                blocklisted_count += 1
            if enriched_count >= max_size:
                print(f"[symbol_enrichment] Reached max universe size {max_size}, stopping enrichment.", flush=True)
                break
        print(f"[symbol_enrichment] Batch {batch_num} complete. Total enriched so far: {enriched_count}", flush=True)
        if enriched_count >= max_size:
            break
        # Removed sleep here to avoid double sleeping, throttling inside provider.fetch_quotes

    log_progress("Enrichment complete", {
        "enriched_count": enriched_count,
        "blocklisted": blocklisted_count,
        "partial_path": PARTIAL_PATH,
        "unfiltered_path": UNFILTERED_PATH,
        "final_path": FINAL_PATH
    })

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Enrichment failed and raised exception", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
