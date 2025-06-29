# tbot_bot/screeners/screener_utils.py
# Utilities to load, validate, and manage the symbol universe cache for TradeBot screeners
# Fully aligned with TradeBot v1.0.0 screener and universe cache specifications
# STRICT: Only universe files built with /stock/symbol, /stock/profile2, /quote endpoints are valid.

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from tbot_bot.support.path_resolver import resolve_universe_cache_path
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.config.env_bot import load_env_bot_config

LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"

class UniverseCacheError(Exception):
    pass

def get_screener_secrets() -> dict:
    """
    Loads and returns the screener_api secrets dict, decrypted from storage.
    Used by all screener modules for uniform secret access.
    Enforced: Must point to a Finnhub API config permitted by endpoint policy.
    """
    try:
        return decrypt_json("screener_api")
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to load screener secrets: {e}")
        return {}

def utc_now() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def load_universe_cache(bot_identity: Optional[str] = None) -> List[Dict]:
    """
    Loads and validates the cached universe JSON.
    Raises UniverseCacheError on missing, invalid, or stale cache.
    Only accepts cache built from allowed endpoints: /stock/symbol, /stock/profile2, /quote.
    Returns list of symbol metadata dicts on success.
    """
    path = resolve_universe_cache_path(bot_identity)
    if not os.path.exists(path):
        LOG.error(f"[screener_utils] Universe cache missing at path: {path}")
        raise UniverseCacheError(f"Universe cache file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to load universe cache JSON: {e}")
        raise UniverseCacheError(f"Failed to load universe cache JSON: {e}")

    if isinstance(data, list):
        if len(data) < 10:
            raise UniverseCacheError("Universe cache is a placeholder/too small; trigger rebuild.")
        data = {
            "schema_version": SCHEMA_VERSION,
            "build_timestamp_utc": utc_now().isoformat(),
            "symbols": data
        }

    if not isinstance(data, dict):
        raise UniverseCacheError("Universe cache JSON root is not an object")

    for key in ("schema_version", "build_timestamp_utc", "symbols"):
        if key not in data:
            raise UniverseCacheError(f"Universe cache missing required key: {key}")

    if data["schema_version"] != SCHEMA_VERSION:
        raise UniverseCacheError(f"Universe cache schema version mismatch: expected {SCHEMA_VERSION}, found {data['schema_version']}")

    try:
        build_time = datetime.fromisoformat(data["build_timestamp_utc"])
        if build_time.tzinfo is None:
            build_time = build_time.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise UniverseCacheError(f"Invalid build_timestamp_utc format: {e}")

    env = load_env_bot_config()
    max_age_days = int(env.get("SCREENER_UNIVERSE_MAX_AGE_DAYS", 3))
    age = utc_now() - build_time
    if age > timedelta(days=max_age_days):
        raise UniverseCacheError(f"Universe cache too old: age {age}, max allowed {max_age_days} days")

    symbols = data["symbols"]
    if not isinstance(symbols, list):
        raise UniverseCacheError("Universe cache 'symbols' is not a list")

    for s in symbols:
        if not all(k in s for k in ("symbol", "exchange", "lastClose", "marketCap")):
            raise UniverseCacheError(f"Symbol entry missing required fields: {s}")

    LOG.info(f"[screener_utils] Loaded universe cache with {len(symbols)} symbols, built at {build_time.isoformat()}")
    return symbols

def save_universe_cache(symbols: List[Dict], bot_identity: Optional[str] = None) -> None:
    """
    Saves the universe cache to disk atomically with schema version and timestamp.
    Only for symbol universes created using /stock/symbol, /stock/profile2, /quote.
    """
    path = resolve_universe_cache_path(bot_identity)
    tmp_path = f"{path}.tmp"

    cache_obj = {
        "schema_version": SCHEMA_VERSION,
        "build_timestamp_utc": utc_now().isoformat(),
        "symbols": symbols
    }

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache_obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to write universe cache to disk: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    LOG.info(f"[screener_utils] Universe cache saved with {len(symbols)} symbols at {path}")

def filter_symbols(
    symbols: List[Dict],
    exchanges: List[str],
    min_price: float,
    max_price: float,
    min_market_cap: float,
    max_market_cap: float,
    blocklist: Optional[List[str]] = None,
    max_size: Optional[int] = None
) -> List[Dict]:
    """
    Filters the input symbol list by exchange, price, market cap, and blocklist.
    Only for symbol metadata pulled from allowed endpoints.
    Optionally truncates the result to max_size by descending market cap.
    """
    blockset = set(blocklist) if blocklist else set()

    filtered = [
        s for s in symbols
        if s.get("exchange") in exchanges
        and isinstance(s.get("lastClose"), (int, float))
        and isinstance(s.get("marketCap"), (int, float))
        and min_price <= s["lastClose"] < max_price
        and min_market_cap <= s["marketCap"] <= max_market_cap
        and s.get("symbol") not in blockset
    ]

    if max_size is not None and len(filtered) > max_size:
        filtered.sort(key=lambda x: x["marketCap"], reverse=True)
        filtered = filtered[:max_size]

    LOG.info(f"[screener_utils] Filtered symbols count: {len(filtered)} after applying exchange, price, market cap, blocklist, and max size filters.")
    return filtered

def load_blocklist(path: Optional[str] = None) -> List[str]:
    """
    Loads blocklist tickers from a text file, one ticker per line, ignoring blank lines and comments (#).
    Returns list of uppercase ticker strings.
    """
    if not path or not os.path.isfile(path):
        LOG.warning(f"[screener_utils] Blocklist file not found or not provided: {path}")
        return []

    blocklist = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    blocklist.append(line.upper())
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to load blocklist file '{path}': {e}")
        return []

    LOG.info(f"[screener_utils] Loaded blocklist with {len(blocklist)} tickers from {path}")
    return blocklist

def is_cache_stale(bot_identity: Optional[str] = None) -> bool:
    """
    Returns True if the universe cache is missing or older than allowed max age.
    """
    try:
        _ = load_universe_cache(bot_identity)
        return False
    except UniverseCacheError:
        return True

def get_cache_build_time(bot_identity: Optional[str] = None) -> Optional[datetime]:
    """
    Returns the UTC build timestamp of the universe cache if present and valid; else None.
    """
    path = resolve_universe_cache_path(bot_identity)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        build_time = datetime.fromisoformat(data["build_timestamp_utc"])
        if build_time.tzinfo is None:
            build_time = build_time.replace(tzinfo=timezone.utc)
        return build_time
    except Exception:
        return None

def get_symbol_set(bot_identity: Optional[str] = None) -> set:
    """
    Returns a set of all symbol strings in the universe cache.
    """
    try:
        symbols = load_universe_cache(bot_identity)
        return set(s.get("symbol") for s in symbols if "symbol" in s)
    except UniverseCacheError:
        return set()
