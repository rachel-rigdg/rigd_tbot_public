# tbot_bot/screeners/symbol_enrichment.py
# Stage 2: Enriches and filters symbols from raw symbols file.
# Reads from symbol_universe.symbols_raw.json; no direct API fetch for symbol list.

import os
import sys
import json
from datetime import datetime, timezone
from tbot_bot.screeners.screener_utils import (
    atomic_append_json, load_blocklist, atomic_append_text
)
from tbot_bot.screeners.screener_filter import normalize_symbols, passes_filter, tofloat
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
            except Exception as e:
                continue
    return syms

def main():
    env = load_env_bot_config()
    try:
        screener_secrets = get_enrichment_provider_creds()
    except Exception as e:
        log_progress("No valid enrichment provider enabled. Aborting enrichment.", {"error": str(e)})
        sys.exit(2)
    name = (screener_secrets.get("SCREENER_NAME") or "").strip().upper()
    if name.endswith("_TXT"):
        log_progress("TXT provider selected as enrichment provider, aborting enrichment.", {"provider": name})
        sys.exit(2)
    ProviderClass = get_provider_class(name)
    if ProviderClass is None:
        log_progress("Provider class not found for enrichment.", {"provider": name})
        sys.exit(2)
    merged_config = env.copy()
    merged_config.update(screener_secrets)
    provider = ProviderClass(merged_config)

    try:
        raw_symbols = load_raw_symbols()
    except Exception as e:
        log_progress("Failed to load raw symbols.", {"error": str(e)})
        sys.exit(2)
    if not raw_symbols:
        log_progress("No raw symbols found.")
        sys.exit(1)

    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

    blocklist = set(load_blocklist(BLOCKLIST_PATH))
    all_symbols = normalize_symbols(raw_symbols)
    symbol_ids = [s["symbol"] for s in all_symbols if "symbol" in s]

    enriched_count = 0
    blocklisted_count = 0
    skipped_missing_financials = 0

    for sym in symbol_ids:
        if sym in blocklist:
            continue
        try:
            quotes = provider.fetch_quotes([sym])
        except Exception:
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|fetch_failed|{datetime.utcnow().isoformat()}Z|{name}\n")
            blocklisted_count += 1
            continue

        if not quotes or not any(q.get("symbol", "") == sym for q in quotes):
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

        # Robust price/cap normalization
        price = q.get("c") or q.get("close") or q.get("lastClose") or q.get("price")
        cap = q.get("marketCap") or q.get("market_cap")
        volume = q.get("v") or q.get("volume")
        price = tofloat(price)
        cap = tofloat(cap)
        # Log if values could not be parsed
        if price is None or cap is None or price <= 0 or cap <= 0:
            atomic_append_text(BLOCKLIST_PATH, f"{sym}|missing_financials|{datetime.utcnow().isoformat()}Z|{name}|raw_price={q.get('c')},{q.get('close')},{q.get('lastClose')},{q.get('price')}|raw_cap={q.get('marketCap')},{q.get('market_cap')}\n")
            skipped_missing_financials += 1
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

        filter_result, skip_reason = passes_filter(
            record,
            min_price,
            max_price,
            min_cap,
            max_cap,
        )
        if not filter_result:
            log_progress("Skipped symbol during filtering", {"symbol": sym, "reason": skip_reason, "record": record})
        if filter_result:
            atomic_append_json(PARTIAL_PATH, record)
            enriched_count += 1

        if enriched_count >= max_size:
            break

    # Do not touch/copy partial to final here: that must be orchestrated externally.

    log_progress("Enrichment complete", {
        "enriched_count": enriched_count,
        "blocklisted": blocklisted_count,
        "skipped_missing_financials": skipped_missing_financials,
        "partial_path": PARTIAL_PATH,
        "unfiltered_path": UNFILTERED_PATH
    })

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Enrichment failed and raised exception", {"error": str(e)})
        sys.exit(1)
