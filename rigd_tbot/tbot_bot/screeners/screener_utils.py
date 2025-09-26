# tbot_bot/screeners/screener_utils.py
# Utility functions for universe cache and credential management, atomic append helpers, and atomic load/save for universe/build outputs.

import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional
import requests  # <<< ADDED

from tbot_bot.support.path_resolver import (
    resolve_universe_cache_path,
    resolve_universe_partial_path,
    resolve_universe_unfiltered_path,
    resolve_screener_blocklist_path,
    get_bot_identity as _get_bot_identity,  # <<< ADDED (identity-aware defaults)
)
from tbot_bot.support.secrets_manager import (
    load_screener_credentials,
    screener_creds_exist as _sm_screener_creds_exist,
)
from tbot_bot.screeners.screener_filter import (
    normalize_symbols, dedupe_symbols
)
from tbot_bot.screeners.blocklist_manager import load_blocklist as load_blocklist_full

LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
UNFILTERED_PATH = resolve_universe_unfiltered_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()

class UniverseCacheError(Exception):
    pass

# <<< ADDED: ensure we default to the active bot identity when none is provided
def _with_identity(bot_identity: Optional[str]) -> Optional[str]:
    """
    Use the provided bot_identity if given; otherwise fall back to the
    currently active bot identity from path_resolver. This keeps readers/writers
    aligned to the same identity-specific universe files.
    """
    try:
        return bot_identity or _get_bot_identity()
    except Exception:
        return bot_identity
# >>>


def atomic_append_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Write newline-delimited JSON object per spec
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def atomic_append_text(path: str, line: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line if line.endswith("\n") else line + "\n")

def atomic_copy_file(src_path: str, dest_path: str):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = dest_path + ".tmp"
    with open(src_path, "rb") as src, open(tmp_path, "wb") as dst:
        while True:
            chunk = src.read(1048576)
            if not chunk:
                break
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    os.replace(tmp_path, dest_path)

def screener_creds_exist() -> bool:
    """
    True only when at least one indexed provider (PROVIDER_XX) exists.
    """
    return _sm_screener_creds_exist()

def get_screener_secrets() -> dict:
    """
    Return the flat generic credentials dict (e.g., PROVIDER_01, SCREENER_API_KEY_01, ...).
    Never raises; returns {} if no file/providers present. Universe gating happens in callers.
    """
    try:
        if not _sm_screener_creds_exist():
            return {}
        return load_screener_credentials()
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to load screener secrets: {e}")
        return {}

def get_universe_screener_secrets() -> dict:
    """
    Return a single, normalized provider config (flat dict) selected for universe operations.
    Fields guaranteed:
      - SCREENER_NAME (uppercase provider name, e.g., 'FINNHUB')
      - SCREENER_API_KEY
      - SCREENER_URL
      - UNIVERSE_ENABLED (bool)
      - TRADING_ENABLED (bool)

    Selection rules:
      - Choose among providers with UNIVERSE_ENABLED=true
      - Prefer FINNHUB if present; otherwise first enabled provider.

    Raises:
        UniverseCacheError if no enabled providers are found.
    """
    def _truthy(v) -> bool:
        return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

    secrets = get_screener_secrets()
    if not secrets:
        raise UniverseCacheError("No screener credentials found.")

    # Discover indexed providers
    providers = []  # list of (name:str, idx:str)
    for k, v in secrets.items():
        if not k.startswith("PROVIDER_"):
            continue
        idx = k.split("_")[-1]
        name = (str(v).strip().upper() if v else "")
        if not name:
            continue
        if _truthy(secrets.get(f"UNIVERSE_ENABLED_{idx}", "false")):
            providers.append((name, idx))

    if not providers:
        raise UniverseCacheError("No screener providers enabled for universe operations. Enable at least one provider (UNIVERSE_ENABLED=true).")

    # Prefer FINNHUB if enabled
    selected_name, selected_idx = next(((n, i) for (n, i) in providers if n == "FINNHUB"), providers[0])

    # Build flat config from selected index (strip suffix)
    suffix = f"_{selected_idx}"
    raw = {}
    for kk, vv in secrets.items():
        if kk.endswith(suffix):
            base = kk[: -len(suffix)]
            raw[base] = vv

    # Normalize expected keys
    out = {
        "SCREENER_NAME": selected_name,
        "SCREENER_API_KEY": raw.get("SCREENER_API_KEY"),
        "SCREENER_URL": raw.get("SCREENER_URL"),
        "UNIVERSE_ENABLED": _truthy(raw.get("UNIVERSE_ENABLED", True)),
        "TRADING_ENABLED": _truthy(raw.get("TRADING_ENABLED", False)),
    }
    return out

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# ADDED: single-source realtime price helper using Screener Credentials
def get_realtime_price(symbol: str, timeout: int = 4) -> float:
    """
    Single source of truth for market prices.
    Uses the currently enabled Screener Credentials (prefers FINNHUB).
    """
    cfg = get_universe_screener_secrets()
    provider = (cfg.get("SCREENER_NAME") or "").upper()

    if provider == "FINNHUB":
        token = (
            cfg.get("SCREENER_API_KEY")
            or cfg.get("API_KEY")
            or cfg.get("FINNHUB_API_KEY")
            or cfg.get("TOKEN")
        )
        if not token:
            raise UniverseCacheError("FINNHUB API key missing in Screener Credentials.")
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": token},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json() or {}
        px = data.get("c")
        if px is None:
            raise UniverseCacheError(f"FINNHUB returned no price for {symbol}: {data}")
        return float(px)

    raise UniverseCacheError(f"Market-data provider '{provider or '<NONE>'}' not supported for quotes.")
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

def utc_now() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def _validate_symbol_record(s: dict) -> bool:
    # minimal schema the rest of the code expects
    return all(k in s for k in ("symbol", "exchange", "lastClose", "marketCap"))

def _load_ndjson_lines(fp) -> List[Dict]:
    out = []
    for line in fp:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, list):
            # Defensive: if a whole array somehow sneaks onto one "line"
            out.extend(obj)
        else:
            out.append(obj)
    return out

def load_universe_cache(bot_identity: Optional[str] = None) -> List[Dict]:
    if not screener_creds_exist():
        raise UniverseCacheError("Screener credentials not configured. Please configure screener credentials in the UI before running screener operations.")
    bot_identity = _with_identity(bot_identity)  # <<< ADDED
    path = resolve_universe_cache_path(bot_identity)
    if not os.path.exists(path):
        LOG.error(f"[screener_utils] Universe cache missing at path: {path}")
        raise UniverseCacheError(f"Universe cache file not found: {path}")

    # --- NEW: accept either NDJSON or JSON array ---
    with open(path, "r", encoding="utf-8") as f:
        # Peek first non-whitespace char
        pos = f.tell()
        head = f.read(256)
        f.seek(pos)
        first = next((ch for ch in head if not ch.isspace()), "")
        if first == "[":
            # JSON array file
            try:
                symbols = json.load(f)
            except Exception as e:
                raise UniverseCacheError(f"Failed to parse universe cache (array): {e}")
            if not isinstance(symbols, list):
                raise UniverseCacheError("Universe cache top-level JSON must be a list.")
        else:
            # NDJSON
            try:
                symbols = _load_ndjson_lines(f)
            except Exception as e:
                raise UniverseCacheError(f"Failed to parse line in universe cache: {e}")

    if not isinstance(symbols, list):
        raise UniverseCacheError("Universe cache did not decode to a list of records.")

    # Validate and filter to dicts
    cleaned: List[Dict] = []
    for s in symbols:
        if not isinstance(s, dict):
            continue
        if _validate_symbol_record(s):
            cleaned.append(s)
        else:
            LOG.warning("[screener_utils] Bad row missing required keys (symbol/exchange/lastClose/marketCap); skipping")

    if len(cleaned) < 10:
        raise UniverseCacheError("Universe cache is a placeholder/too small; trigger rebuild.")

    LOG.info(f"[screener_utils] Loaded universe cache with {len(cleaned)} symbols from {path}")
    return cleaned

def load_partial_cache() -> List[Dict]:
    path = resolve_universe_partial_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []

def load_unfiltered_cache() -> List[Dict]:
    path = UNFILTERED_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []

def save_universe_cache(symbols: List[Dict], bot_identity: Optional[str] = None) -> None:
    bot_identity = _with_identity(bot_identity)  # <<< ADDED
    path = resolve_universe_cache_path(bot_identity)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            # Always write NDJSON for consistency
            for s in symbols:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to write universe cache to disk: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    LOG.info(f"[screener_utils] Universe cache saved with {len(symbols)} symbols at {path}")

# -----------------------------
# NEW: safe loader + stale check
# -----------------------------
def safe_load_universe_cache(bot_identity: Optional[str] = None) -> Optional[List[Dict]]:
    """
    Best-effort loader that quarantines corrupt/invalid cache files.
    Returns None when cache is missing/invalid so callers can rebuild.
    """
    try:
        return load_universe_cache(bot_identity)
    except UniverseCacheError as e:
        msg = str(e)
        bot_identity = _with_identity(bot_identity)  # <<< ADDED
        path = resolve_universe_cache_path(bot_identity)
        # Treat genuinely corrupt/invalid files as corruption → quarantine.
        # But do NOT quarantine just because it's a JSON array or "too small".
        if any(key in msg for key in (
            "Failed to parse line",
            "Failed to parse universe cache (array)",
            "top-level JSON must be a list",
            "did not decode to a list",
        )):
            try:
                if os.path.exists(path):
                    bad_path = f"{path}.bad"
                    os.replace(path, bad_path)
                    LOG.warning(f"[screener_utils] Quarantined corrupt universe cache to {bad_path}")
            except Exception as qe:
                LOG.error(f"[screener_utils] Failed to quarantine corrupt cache '{path}': {qe}")
        return None

def load_blocklist(path: Optional[str] = None) -> List[str]:
    if not path:
        blockset = load_blocklist_full()
        return list(blockset)
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
                sym = line.split("|", 1)[0].upper()
                blocklist.append(sym)
    except Exception as e:
        LOG.error(f"[screener_utils] Failed to load blocklist file '{path}': {e}")
        return []
    LOG.info(f"[screener_utils] Loaded blocklist with {len(blocklist)} tickers from {path}")
    return blocklist

def is_cache_stale(bot_identity: Optional[str] = None) -> bool:
    try:
        # Use safe loader so corrupted-but-present files are treated as stale
        symbols = safe_load_universe_cache(bot_identity)
        return symbols is None
    except Exception:
        return True

def get_cache_build_time(bot_identity: Optional[str] = None) -> Optional[datetime]:
    bot_identity = _with_identity(bot_identity)  # <<< ADDED
    path = resolve_universe_cache_path(bot_identity)
    if not os.path.exists(path):
        return None
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except Exception:
        return None

def get_symbol_set(bot_identity: Optional[str] = None) -> set:
    try:
        symbols = load_universe_cache(bot_identity)
        return set(s.get("symbol") for s in symbols if "symbol" in s)
    except UniverseCacheError:
        return set()
