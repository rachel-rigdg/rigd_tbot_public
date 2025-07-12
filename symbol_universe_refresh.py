# tbot_bot/screeners/symbol_universe_refresh.py
# Writes normalized symbol universe to unfiltered.json ONLY. No enrichment, no filtering, no blocklisting. Partial/final handled by symbol_enrichment.py.

import sys
import json
import os
from datetime import datetime, timezone
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import atomic_append_json, load_blocklist
from tbot_bot.screeners.screener_filter import normalize_symbols
from tbot_bot.support.path_resolver import (
    resolve_universe_unfiltered_path,
    resolve_universe_log_path,
)
from tbot_bot.support.secrets_manager import (
    get_screener_credentials_path,
    load_screener_credentials
)
from tbot_bot.screeners.provider_registry import get_provider_class

UNFILTERED_PATH = resolve_universe_unfiltered_path()
LOG_PATH = resolve_universe_log_path()

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

    # Write ONLY normalized symbols to unfiltered.json
    count = 0
    for sym_obj in normalize_symbols(syms):
        sym = sym_obj.get("symbol")
        if not sym:
            continue
        atomic_append_json(UNFILTERED_PATH, sym_obj)
        count += 1

    log_progress("Universe symbol source written to unfiltered.json", {"written_count": count})

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Universe build failed and raised exception", {"error": str(e)})
        sys.exit(1)
