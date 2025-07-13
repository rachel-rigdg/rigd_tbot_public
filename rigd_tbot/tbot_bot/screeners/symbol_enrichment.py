# tbot_bot/screeners/symbol_enrichment.py
# Stage 2: Enriches and filters symbols from raw symbols file.
# Reads from symbol_universe.symbols_raw.json; no direct API fetch for symbol list.

import os
import sys
import json
from datetime import datetime, timezone
from tbot_bot.screeners.screener_utils import (
    atomic_append_json, load_blocklist, atomic_append_text, atomic_copy_file
)
from tbot_bot.screeners.screener_filter import normalize_symbols, passes_filter
from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path, resolve_universe_cache_path, resolve_screener_blocklist_path,
    resolve_universe_log_path, resolve_universe_unfiltered_path, resolve_universe_raw_path
)
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.provider_registry import get_provider_class

PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()
LOG_PATH = resolve_universe_log_path()
UNFILTERED_PATH = resolve_universe_unfiltered_path()
RAW_PATH = resolve_universe_raw_path()

def log_progress(msg, details=None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")

def get_enrichment_provider_creds():
    all_creds = load_screener_credentials()
    provider_indices = []
    for k, v in all_creds.items():
        if k.startswith("PROVIDER_"):
            idx = k.split("_")[-1]
            enrichment_enabled = all_creds.get(f"ENRICHMENT_ENABLED_{idx}", "false")
            screener_name = all_creds.get(f"SCREENER_NAME_{idx}", "")
            if enrichment_enabled is not None and enrichment_enabled.lower() == "true" and screener_name and not screener_name.upper().endswith("_TXT"):
                provider_indices.append(idx)
    if not provider_indices:
        raise RuntimeError("No valid enrichment provider enabled for universe enrichment. Enable at least one API provider (not *_TXT) in the credential admin with ENRICHMENT_ENABLED checked.")
    idx = provider_indices[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

def load_raw_symbols():
    if not os.path.exists(RAW_PATH):
        raise RuntimeError(f"Raw symbol universe not found: {RAW_PATH}")
    syms = []
    with open(RAW_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                syms.append(json.loads(line))
            except Exception:
                continue
    return syms

def main():
    print("[DEBUG] symbol_enrichment.py main() starting", flush=True)
    env = load_env_bot_config()
    bot_identity = env.get("BOT_IDENTITY_STRING", None)
    try:
        screener_secrets = get_enrichment_provider_creds()
    except Exception as e:
        log_progress("No valid enrichment provider enabled. Aborting enrichment.", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(2)
    name = (screener_secrets.get("SCREENER_NAME") or "").strip().upper()
    print(f"[DEBUG] SCREENER_NAME: {name}", flush=True)
    if name.endswith("_TXT"):
        log_progress("TXT provider selected as enrichment provider, aborting enrichment.", {"provider": name})
        print(f"ERROR: TXT providers (like {name}) cannot be used for enrichment. Enable a data API provider (e.g. Finnhub, IBKR, Yahoo).", flush=True)
        sys.exit(2)
    ProviderClass = get_provider_class(name)
    if ProviderClass is None:
        print(f"ERROR: No provider class mapping found for SCREENER_NAME '{name}'", flush=True)
        log_progress("Provider class not found for enrichment.", {"provider": name})
        sys.exit(2)
    merged_config = env.copy()
    merged_config.update(screener_secrets)
    print("[DEBUG_CREDENTIALS]", json.dumps(merged_config, indent=2), flush=True)
    provider = ProviderClass(merged_config)

    try:
        raw_symbols = load_raw_symbols()
        print(f"[DEBUG] loaded {len(raw_symbols)} raw symbols from {RAW_PATH}", flush=True)
    except Exception as e:
        log_progress("Failed to load raw symbols.", {"error": str(e)})
        print(f"ERROR: failed to load raw symbols: {e}", flush=True)
        sys.exit(2)

    if not raw_symbols:
        print("[DEBUG] No raw symbols found.", flush=True)
        log_progress("No raw symbols found.")
        sys.exit(1)
    exchanges = [e.strip().upper() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NASDAQ,NYSE").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

    blocklist = set(load_blocklist(BLOCKLIST_PATH))
    all_symbols = [s for s in normalize_symbols(raw_symbols) if s.get("symbol") not in blocklist]
    symbol_ids = [s["symbol"] for s in all_symbols if "symbol" in s]
    enriched_count = 0
    blocklisted_count = 0

    for i, sym in enumerate(symbol_ids):
        log_progress("Processing symbol", {"symbol_num": i+1, "total": len(symbol_ids), "symbol": sym})
        try:
            quotes = provider.fetch_quotes([sym])
        except Exception as e:
            log_progress("Failed to fetch quote for symbol", {"error": str(e), "symbol": sym})
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|fetch_failed|{datetime.utcnow().isoformat()}Z|{name}\n")
            blocklisted_count += 1
            continue
        if not quotes or not any(q.get("symbol", "") == sym for q in quotes):
            log_progress("No quote data for symbol", {"symbol": sym})
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|no_data_from_api|{datetime.utcnow().isoformat()}Z|{name}\n")
            blocklisted_count += 1
            continue
        quote_map = {q["symbol"]: q for q in quotes if "symbol" in q}
        s = next((x for x in all_symbols if x.get("symbol") == sym), None)
        if not s:
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|no_source|{datetime.utcnow().isoformat()}Z|{name}\n")
            blocklisted_count += 1
            continue
        q = quote_map.get(sym)
        if not q:
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|no_quote|{datetime.utcnow().isoformat()}Z|{name}\n")
            blocklisted_count += 1
            continue
        price = q.get("c") or q.get("close") or q.get("lastClose") or q.get("price")
        cap = q.get("marketCap") or q.get("market_cap")
        volume = q.get("v") or q.get("volume")
        try:
            price = float(price)
            cap = float(cap) if cap is not None else None
        except Exception:
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|invalid_fields|{datetime.utcnow().isoformat()}Z|{name}\n")
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
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|{reason}|{datetime.utcnow().isoformat()}Z|{name}\n")
            blocklisted_count += 1
        if enriched_count >= max_size:
            log_progress("Reached max universe size, stopping enrichment.", {"max_size": max_size})
            break

    atomic_copy_file(PARTIAL_PATH, FINAL_PATH)

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
