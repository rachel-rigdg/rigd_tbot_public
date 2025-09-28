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
from tbot_bot.screeners.screener_filter import normalize_symbols, filter_symbols, tofloat, normalize_market_cap
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
        try:
            record += " | " + json.dumps(details, ensure_ascii=False)
        except Exception:
            record += " | (details serialization failed)"
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as logf:
            logf.write(record + "\n")
    except Exception:
        # best-effort logging
        pass

def get_enrichment_provider_creds():
    def _truthy(v) -> bool:
        return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

    all_creds = load_screener_credentials() or {}
    provider_indices = []
    for k, v in all_creds.items():
        if k.startswith("PROVIDER_"):
            idx = k.split("_")[-1]
            enrichment_enabled = all_creds.get(f"ENRICHMENT_ENABLED_{idx}", "false")
            screener_name = all_creds.get(f"SCREENER_NAME_{idx}", "")
            if _truthy(enrichment_enabled) and screener_name and not str(screener_name).upper().endswith("_TXT"):
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

def _atomic_write_json(path: str, payload) -> None:
    """
    Atomically write a single JSON payload (array or object) to disk.
    Ensures one valid JSON document (not NDJSON), compatible with orchestrator.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".staged.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    # Best-effort directory fsync
    try:
        dfd = os.open(os.path.dirname(path), os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        pass

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

    # Parse allowed exchanges from env (optional)
    exchanges_env = (env.get("SCREENER_UNIVERSE_EXCHANGES", "") or "").strip()
    allowed_exchanges = [e.strip().upper() for e in exchanges_env.split(",") if e.strip()] or None

    blocklist = set(load_blocklist(BLOCKLIST_PATH))
    all_symbols = normalize_symbols(raw_symbols)
    symbol_ids = [s["symbol"] for s in all_symbols if "symbol" in s]

    # Counters
    enriched_count = 0
    blocklisted_count = 0        # only pre-existing blocklist hits
    missed_api_count = 0         # API/quote misses (not blocklisted)
    skipped_missing_financials = 0

    # Accumulate into memory and write ONE JSON per file (not NDJSON)
    unfiltered_records = []

    # --- Enrichment phase (no filtering here; centralized filter used later) ---
    for sym in symbol_ids:
        if sym in blocklist:
            blocklisted_count += 1
            continue
        try:
            quotes = provider.fetch_quotes([sym])
        except Exception as e:
            # Do NOT mutate blocklist on API failures; just record
            missed_api_count += 1
            log_progress("Quote fetch failed", {"symbol": sym, "provider": name, "error": str(e)})
            continue

        if not quotes or not any(q.get("symbol", "") == sym for q in quotes):
            missed_api_count += 1
            log_progress("No data from API", {"symbol": sym, "provider": name})
            continue

        quote_map = {q["symbol"]: q for q in quotes if "symbol" in q}
        s = next((x for x in all_symbols if x.get("symbol") == sym), None)
        if not s:
            missed_api_count += 1
            log_progress("No source record for symbol after normalization", {"symbol": sym})
            continue

        q = quote_map.get(sym)
        if not q:
            missed_api_count += 1
            log_progress("No quote found in provider response", {"symbol": sym})
            continue

        # Only use previous close (c) and previous close volume if available; never real-time
        price_raw = q.get("pc") or q.get("c") or q.get("close") or q.get("lastClose") or q.get("price")
        cap_raw = q.get("marketCap") or q.get("market_cap")
        volume = q.get("volume") or q.get("v")

        price = tofloat(price_raw)
        cap_val = tofloat(cap_raw)
        cap_norm = normalize_market_cap(cap_val) if cap_val is not None else None

        # Skip record if values could not be parsed (do NOT add to blocklist)
        if price is None or cap_norm is None or price <= 0 or cap_norm <= 0:
            skipped_missing_financials += 1
            log_progress(
                "Missing/invalid financials during enrichment",
                {
                    "symbol": sym,
                    "provider": name,
                    "raw_price": [q.get('c'), q.get('pc'), q.get('close'), q.get('lastClose'), q.get('price')],
                    "raw_cap": [q.get('marketCap'), q.get('market_cap')],
                },
            )
            continue

        record = dict(s)
        record["lastClose"] = price
        record["marketCap"] = cap_norm
        if volume is not None:
            record["volume"] = volume
        for k in q:
            if k not in record:
                record[k] = q[k]

        unfiltered_records.append(record)

    # --- Centralized filtering step (single pass) ---
    partial_records = filter_symbols(
        unfiltered_records,
        min_price,
        max_price,
        min_cap,
        max_cap,
        allowed_exchanges=allowed_exchanges,
        max_size=max_size,
        broker_obj=None,
    )
    enriched_count = len(partial_records)

    # Write a SINGLE JSON array per file (compatible with orchestrator reader)
    _atomic_write_json(UNFILTERED_PATH, unfiltered_records)
    _atomic_write_json(PARTIAL_PATH, partial_records)

    # Do not touch/copy partial to final here: that must be orchestrated externally.

    log_progress("Enrichment complete", {
        "enriched_count": enriched_count,
        "blocklisted": blocklisted_count,
        "missed_api": missed_api_count,
        "skipped_missing_financials": skipped_missing_financials,
        "unfiltered_count": len(unfiltered_records),
        "partial_count": len(partial_records),
        "partial_path": PARTIAL_PATH,
        "unfiltered_path": UNFILTERED_PATH
    })

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Enrichment failed and raised exception", {"error": str(e)})
        sys.exit(1)
