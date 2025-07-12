# tbot_bot/screeners/screener_utils.py
# Utility functions for universe cache and credential management.
# 100% compliant with modular, usage-flagged, multi-provider screener credentials system.

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from tbot_bot.support.path_resolver import (
    resolve_universe_cache_path,
    resolve_universe_partial_path,
    resolve_screener_blocklist_path
)
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support.secrets_manager import get_screener_credentials_path, load_screener_credentials
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_filter import (
    normalize_symbols, filter_symbols as core_filter_symbols, dedupe_symbols
)
from tbot_bot.screeners.blocklist_manager import load_blocklist as load_blocklist_full

LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
UNFILTERED_PATH = "tbot_bot/output/screeners/symbol_universe.unfiltered.json"
BLOCKLIST_PATH = resolve_screener_blocklist_path()

class UniverseCacheError(Exception):
    pass

def screener_creds_exist() -> bool:
    creds_path = get_screener_credentials_path()
    return os.path.exists(creds_path)

def get_screener_secrets() -> dict:
    if not screener_creds_exist():
        raise UniverseCacheError("Screener credentials not configured. Please configure screener credentials in the UI before running screener operations.")
    try:
        return decrypt_json("screener_api.json.enc")
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to load screener secrets: {e}")
        return {}

def get_universe_screener_secrets() -> dict:
    """
    Loads the first provider with UNIVERSE_ENABLED == 'true' (case-insensitive).
    Returns flat key/value dict for that provider, ready for direct injection.
    """
    all_creds = load_screener_credentials()
    provider_indices = [
        k.split("_")[-1]
        for k, v in all_creds.items()
        if k.startswith("PROVIDER_")
           and all_creds.get(f"UNIVERSE_ENABLED_{k.split('_')[-1]}", "false").upper() == "TRUE"
    ]
    if not provider_indices:
        raise UniverseCacheError("No screener providers enabled for universe build. Please enable at least one in the credential admin.")
    idx = provider_indices[0]
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

def utc_now() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def load_universe_cache(bot_identity: Optional[str] = None) -> List[Dict]:
    if not screener_creds_exist():
        raise UniverseCacheError("Screener credentials not configured. Please configure screener credentials in the UI before running screener operations.")
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
        build_time_str = data["build_timestamp_utc"]
        if build_time_str.endswith("Z"):
            build_time_str = build_time_str.replace("Z", "+00:00")
        build_time = datetime.fromisoformat(build_time_str)
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

def load_partial_cache() -> List[Dict]:
    path = resolve_universe_partial_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("symbols", [])
    except Exception:
        return []

def load_unfiltered_cache() -> List[Dict]:
    if not os.path.exists(UNFILTERED_PATH):
        return []
    try:
        with open(UNFILTERED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("symbols", [])
    except Exception:
        return []

def save_universe_cache(symbols: List[Dict], bot_identity: Optional[str] = None) -> None:
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
    max_size: Optional[int] = None,
    broker_obj=None
) -> List[Dict]:
    """
    Filters symbols using core filtering logic.
    Supports filtering by exchange, price range, market cap, blocklist exclusion, and broker fractional eligibility.
    Returns filtered and deduplicated list of symbol dicts.
    """
    # Fractional trading eligibility check disabled during universe build per spec
    return core_filter_symbols(
        symbols,
        exchanges,
        min_price,
        max_price,
        min_market_cap,
        max_market_cap,
        blocklist,
        max_size,
        broker_obj=None  # Force None to skip fractional checks at universe build stage
    )

def load_blocklist(path: Optional[str] = None) -> List[str]:
    """
    Loads blocklist from the specified path or full blocklist manager.
    Returns list of blocklisted symbol strings (uppercase).
    """
    if not path:
        bl_dict = load_blocklist_full()
        return list(bl_dict.keys())
    if not os.path.isfile(path):
        LOG.warning(f"[screener_utils] Blocklist file not found or not provided: {path}")
        return []
    blocklist = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                sym = line.split(",", 1)[0].upper()
                blocklist.append(sym)
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to load blocklist file '{path}': {e}")
        return []
    LOG.info(f"[screener_utils] Loaded blocklist with {len(blocklist)} tickers from {path}")
    return blocklist

def is_cache_stale(bot_identity: Optional[str] = None) -> bool:
    """
    Determines if the universe cache is stale or invalid.
    Returns True if cache is missing or invalid; False otherwise.
    """
    try:
        _ = load_universe_cache(bot_identity)
        return False
    except UniverseCacheError:
        return True

def get_cache_build_time(bot_identity: Optional[str] = None) -> Optional[datetime]:
    """
    Returns the datetime of the universe cache build or None if unavailable.
    """
    path = resolve_universe_cache_path(bot_identity)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        build_time_str = data["build_timestamp_utc"]
        if build_time_str.endswith("Z"):
            build_time_str = build_time_str.replace("Z", "+00:00")
        build_time = datetime.fromisoformat(build_time_str)
        if build_time.tzinfo is None:
            build_time = build_time.replace(tzinfo=timezone.utc)
        return build_time
    except Exception:
        return None

def get_symbol_set(bot_identity: Optional[str] = None) -> set:
    """
    Returns a set of symbols currently in the universe cache.
    """
    try:
        symbols = load_universe_cache(bot_identity)
        return set(s.get("symbol") for s in symbols if "symbol" in s)
    except UniverseCacheError:
        return set()
