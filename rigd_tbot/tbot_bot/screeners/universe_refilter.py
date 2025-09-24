# tbot_bot/screeners/universe_refilter.py

import os
import sys
import json
from tbot_bot.screeners.screener_filter import normalize_symbols, passes_filter, filter_symbols
from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path, resolve_universe_cache_path, resolve_universe_unfiltered_path
)
from tbot_bot.config.env_bot import load_env_bot_config

PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
UNFILTERED_PATH = resolve_universe_unfiltered_path()

def _load_unfiltered(path: str):
    """
    Load unfiltered universe supporting BOTH formats:
    - JSON array (single document)
    - NDJSON (one JSON object per line)
    Returns: list[dict]
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = f.read().strip()
        if not data:
            return []
        # Try JSON array/object first
        try:
            obj = json.loads(data)
            if isinstance(obj, list):
                return obj
            # single object -> wrap
            return [obj]
        except Exception:
            pass
    # Fallback to NDJSON
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

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
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

    exchanges_env = (env.get("SCREENER_UNIVERSE_EXCHANGES", "") or "").strip()
    allowed_exchanges = [e.strip().upper() for e in exchanges_env.split(",") if e.strip()] or None

    try:
        syms = _load_unfiltered(UNFILTERED_PATH)
    except Exception as e:
        print(str(e))
        sys.exit(1)

    # Use centralized filter (handles normalization, exchange whitelist, auto-ranging, and max_size)
    filtered = filter_symbols(
        syms,
        min_price,
        max_price,
        min_cap,
        max_cap,
        allowed_exchanges=allowed_exchanges,
        max_size=max_size,
        broker_obj=None
    )

    # Write a SINGLE JSON array (no NDJSON)
    _atomic_write_json(PARTIAL_PATH, filtered)

    # Finalize with atomic copy
    from tbot_bot.screeners.screener_utils import atomic_copy_file
    atomic_copy_file(PARTIAL_PATH, FINAL_PATH)
    print(f"Filtered {len(filtered)} symbols to {PARTIAL_PATH}")

if __name__ == "__main__":
    main()
