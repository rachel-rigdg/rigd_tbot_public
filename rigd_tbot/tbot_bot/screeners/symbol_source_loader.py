# tbot_bot/screeners/symbol_source_loader.py
# 100% compliant: Only uses provider adapters and API credentials from get_universe_screener_secrets().
# No TXT/CSV-based symbol sources. No direct Yahoo or legacy loads.

from typing import List, Dict

from tbot_bot.screeners.screener_utils import get_universe_screener_secrets
from tbot_bot.screeners.provider_registry import get_provider_class

def load_api_provider_symbols() -> List[Dict]:
    """
    Loads symbols using only the enabled provider adapter with UNIVERSE_ENABLED == "true".
    Credentials are injected from get_universe_screener_secrets.
    """
    provider_cfg = get_universe_screener_secrets()
    provider_name = (provider_cfg.get("SCREENER_NAME") or "").strip().upper()
    if not provider_name or provider_name.endswith("_TXT"):
        raise RuntimeError("No valid API provider enabled for universe build. Enable a provider with UNIVERSE_ENABLED via the /screener_credentials admin UI.")
    ProviderClass = get_provider_class(provider_name)
    if ProviderClass is None:
        raise RuntimeError(f"No provider class found for SCREENER_NAME '{provider_name}'.")
    provider = ProviderClass(provider_cfg)
    # Adapter's fetch_symbols always returns normalized list with required fields.
    symbols = provider.fetch_symbols()
    return dedupe_symbols(symbols)

def dedupe_symbols(symbols: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for s in symbols:
        key = s.get("symbol")
        if key and key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped

if __name__ == "__main__":
    syms = load_api_provider_symbols()
    print(f"Loaded {len(syms)} unique symbols from API provider")
    import json
    with open("symbol_source_merged.json", "w", encoding="utf-8") as f:
        json.dump(syms, f, indent=2)
