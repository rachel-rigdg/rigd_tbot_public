# tbot_bot/screeners/universe_refilter.py

import os
import sys
import json
from datetime import datetime
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

def _stage_with_timestamp(symbols):
    """
    Build final payload with build_timestamp_utc, preserving schema.
    """
    return {
        "symbols": list(symbols or []),
        "build_timestamp_utc": datetime.utcnow().isoformat() + "Z",
    }

def _atomic_publish_final_from_partial(partial_path: str, final_path: str) -> None:
    """
    Read PARTIAL (array or object), inject timestamp, and atomically publish FINAL.
    Preserve last-good on any failure (i.e., do not modify FINAL unless replace succeeds).
    """
    with open(partial_path, "r", encoding="utf-8") as f:
        content = f.read().strip() or "[]"
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            symbols = parsed.get("symbols", [])
        elif isinstance(parsed, list):
            symbols = parsed
        else:
            symbols = []
    except Exception:
        # If partial is malformed, refuse to publish
        raise RuntimeError("Partial universe is not valid JSON; refusing to publish.")

    payload = _stage_with_timestamp(symbols)
    _atomic_write_json(final_path, payload)

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

    try:
        # Write a SINGLE JSON array (no NDJSON)
        _atomic_write_json(PARTIAL_PATH, filtered)

        # Finalize with atomic publish (inject timestamp); preserve last-good on failure
        _atomic_publish_final_from_partial(PARTIAL_PATH, FINAL_PATH)
        print(f"Filtered {len(filtered)} symbols to {PARTIAL_PATH} and published final.")
    except Exception as e:
        # Do NOT touch FINAL_PATH on failure
        print(f"ERROR during re-filter publish: {e}")
        sys.exit(2)

if __name__ == "__main__":
    main()
