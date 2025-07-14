# tbot_bot/screeners/symbol_universe_raw_builder.py
# Stage 1: Downloads the full raw symbol universe via a single provider API call.
# Writes the complete raw symbol payload to symbol_universe.symbols_raw.json (newline-delimited JSON).
# All operations are atomic, crash-resumable, and audit-logged.
# No filtering, no enrichment, no blocklist applied here.

import os
import sys
import json
from datetime import datetime, timezone
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.path_resolver import resolve_universe_raw_path, resolve_universe_log_path
from tbot_bot.screeners.provider_registry import get_provider_class

RAW_PATH = resolve_universe_raw_path()
LOG_PATH = resolve_universe_log_path()

def log_progress(msg, details=None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")

def get_raw_provider_creds():
    all_creds = load_screener_credentials()
    provider_indices = []
    for k, v in all_creds.items():
        if k.startswith("PROVIDER_"):
            idx = k.split("_")[-1]
            universe_enabled = all_creds.get(f"UNIVERSE_ENABLED_{idx}", "false")
            screener_name = all_creds.get(f"SCREENER_NAME_{idx}", "")
            if universe_enabled is not None and universe_enabled.lower() == "true" and screener_name and not screener_name.upper().endswith("_TXT"):
                provider_indices.append(idx)
    if not provider_indices:
        raise RuntimeError("No valid universe provider enabled. Enable at least one API provider (not *_TXT) in the credential admin with UNIVERSE_ENABLED checked.")
    idx = provider_indices[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

def main():
    log_progress("symbol_universe_raw_builder.py started")
    try:
        screener_secrets = get_raw_provider_creds()
    except Exception as e:
        log_progress("No valid universe provider enabled. Aborting raw build.", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(2)
    name = (screener_secrets.get("SCREENER_NAME") or "").strip().upper()
    if name.endswith("_TXT"):
        log_progress("TXT provider selected as universe provider, aborting raw build.", {"provider": name})
        print(f"ERROR: TXT providers (like {name}) cannot be used for universe build. Enable a data API provider (e.g. Finnhub).", flush=True)
        sys.exit(2)
    ProviderClass = get_provider_class(name)
    if ProviderClass is None:
        log_progress(f"No provider class mapping found for SCREENER_NAME '{name}'", {"provider": name})
        print(f"ERROR: No provider class mapping found for SCREENER_NAME '{name}'", flush=True)
        sys.exit(2)
    provider = ProviderClass(screener_secrets)
    try:
        raw_symbols = provider.fetch_symbols()
    except Exception as e:
        log_progress("Provider fetch_symbols() failed, aborting.", {"error": str(e)})
        print(f"ERROR: fetch_symbols failed: {e}", flush=True)
        sys.exit(2)
    if not raw_symbols:
        log_progress("Provider returned no symbols.")
        sys.exit(1)
    tmp_path = RAW_PATH + ".tmp"
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        for s in raw_symbols:
            f.write(json.dumps(s) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, RAW_PATH)
    log_progress("Raw symbol universe written", {"raw_path": RAW_PATH, "count": len(raw_symbols)})
    print(f"Raw symbol universe build complete: {len(raw_symbols)} symbols written to {RAW_PATH}", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Raw universe build failed and raised exception", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
