# tbot_bot/screeners/symbol_universe_refresh.py
# Nightly job to build, filter, and atomically write the symbol universe cache for all screeners
# Fully aligned with RIGD TradeBot screener/cache specification
# Updated: STRICT Finnhub API endpoint enforcement — only /stock/symbol, /stock/profile2, /quote allowed. All other endpoints forbidden.
# API rate limiting uses SLEEP_TIME from env config.
# Writes progress/partial and heartbeat to output/screeners/universe_ops.log and symbol_universe.partial.json

import sys
import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict

from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import (
    save_universe_cache, filter_symbols, load_blocklist, UniverseCacheError, get_screener_secrets
)
from tbot_bot.support.path_resolver import (
    resolve_universe_cache_path,
    resolve_universe_partial_path,
    resolve_universe_log_path
)

LOG_PATH = resolve_universe_log_path()

def log_progress(msg: str, details: dict = None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")
    # Also print for CLI/ops feedback
    print(record)

def write_partial(symbols, meta=None):
    partial_path = resolve_universe_partial_path()
    cache_obj = {
        "schema_version": "1.0.0",
        "build_timestamp_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "symbols": symbols
    }
    if meta:
        cache_obj["meta"] = meta
    with open(partial_path, "w", encoding="utf-8") as pf:
        json.dump(cache_obj, pf, indent=2)

def normalize_symbol_data(symbols: List[Dict]) -> List[Dict]:
    """
    Normalizes lastClose and marketCap to float or None. Discards lastClose <= 0 or invalid.
    """
    normed = []
    for s in symbols:
        try:
            lc_raw = s.get("lastClose")
            mc_raw = s.get("marketCap")
            # Convert to float if possible, else None
            lc = float(lc_raw) if lc_raw not in (None, '', 'None', 'null') else None
            mc = float(mc_raw) if mc_raw not in (None, '', 'None', 'null') else None
        except Exception:
            lc = None
            mc = None
        s["lastClose"] = lc
        s["marketCap"] = mc
        # Only include if lastClose is not None and > 0
        if lc is not None and lc > 0:
            normed.append(s)
    return normed

def fetch_broker_symbol_metadata() -> List[Dict]:
    env = load_env_bot_config()
    screener_secrets = get_screener_secrets()
    screener_name = (screener_secrets.get("SCREENER_NAME") or "FINNHUB").strip().upper()
    if screener_name == "FINNHUB":
        return fetch_finnhub_symbols(screener_secrets, env)
    elif screener_name == "TRADIER":
        return fetch_tradier_symbols(screener_secrets, env)
    elif screener_name == "IBKR":
        return fetch_ibkr_symbols(screener_secrets, env)
    else:
        raise RuntimeError(f"Unsupported SCREENER_NAME: {screener_name}")

def fetch_finnhub_symbols(secrets, env):
    import requests
    SCREENER_API_KEY = secrets.get("SCREENER_API_KEY") or secrets.get("SCREENER_TOKEN")
    SCREENER_URL = secrets.get("SCREENER_URL", "https://finnhub.io/api/v1/")
    SCREENER_USERNAME = secrets.get("SCREENER_USERNAME", "")
    SCREENER_PASSWORD = secrets.get("SCREENER_PASSWORD", "")
    SLEEP_TIME = float(env.get("SLEEP_TIME", 0.3))
    PARTIAL_WRITE_FREQ = int(env.get("UNIVERSE_PARTIAL_WRITE_FREQ", 100))
    if not SCREENER_API_KEY:
        raise RuntimeError("SCREENER_API_KEY not set in screener secrets/config")
    symbols = []
    total_count = 0
    for exch in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(","):
        url = f"{SCREENER_URL.rstrip('/')}/stock/symbol?exchange={exch.strip()}&token={SCREENER_API_KEY}"
        auth = (SCREENER_USERNAME, SCREENER_PASSWORD) if SCREENER_USERNAME and SCREENER_PASSWORD else None
        r = requests.get(url, auth=auth)
        if r.status_code != 200:
            log_progress(f"Failed to fetch symbol list for exchange {exch}", {"status": r.status_code})
            continue
        for s in r.json():
            symbol = s.get("symbol")
            profile_url = f"{SCREENER_URL.rstrip('/')}/stock/profile2?symbol={symbol}&token={SCREENER_API_KEY}"
            profile = requests.get(profile_url, auth=auth)
            p = profile.json() if profile.status_code == 200 else {}
            time.sleep(SLEEP_TIME)
            quote_url = f"{SCREENER_URL.rstrip('/')}/quote?symbol={symbol}&token={SCREENER_API_KEY}"
            quote = requests.get(quote_url, auth=auth)
            q = quote.json() if quote.status_code == 200 else {}
            time.sleep(SLEEP_TIME)
            symbols.append({
                "symbol": symbol,
                "exchange": exch.strip(),
                "lastClose": q.get("pc") or q.get("c"),
                "marketCap": p.get("marketCapitalization"),
                "name": p.get("name") or s.get("description") or "",
                "sector": p.get("finnhubIndustry") or "",
                "industry": "",
                "volume": q.get("v") or 0
            })
            total_count += 1
            if total_count % PARTIAL_WRITE_FREQ == 0:
                log_progress(f"Universe build progress: {total_count} symbols fetched", {"partial": True})
                write_partial(symbols)
    return symbols

def fetch_tradier_symbols(secrets, env):
    import requests
    api_key = secrets.get("SCREENER_API_KEY") or secrets.get("SCREENER_TOKEN")
    username = secrets.get("SCREENER_USERNAME", "")
    password = secrets.get("SCREENER_PASSWORD", "")
    url = secrets.get("SCREENER_URL", "https://api.tradier.com/v1/markets/symbols")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    auth = (username, password) if username and password else None
    r = requests.get(url, headers=headers, auth=auth)
    if r.status_code != 200:
        raise RuntimeError("Failed to fetch symbols from Tradier")
    data = r.json().get("symbols", {}).get("symbol", [])
    results = []
    for s in data:
        results.append({
            "symbol": s.get("symbol", ""),
            "exchange": s.get("exchange", ""),
            "lastClose": None,
            "marketCap": None,
            "name": s.get("description", ""),
            "sector": "",
            "industry": "",
            "volume": 0
        })
    return results

def fetch_ibkr_symbols(secrets, env):
    # Placeholder for future IBKR universe. Strict endpoint use to be specified as required.
    return []

def main():
    env = load_env_bot_config()
    exchanges = [e.strip() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 5))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 100))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 2_000_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))
    blocklist_path = env.get("SCREENER_UNIVERSE_BLOCKLIST_PATH", None)
    bot_identity = env.get("BOT_IDENTITY_STRING", None)

    log_progress("Universe build parameters", {
        "exchanges": exchanges,
        "price": [min_price, max_price],
        "cap": [min_cap, max_cap],
        "max_size": max_size,
        "blocklist": blocklist_path
    })

    try:
        symbols_raw = fetch_broker_symbol_metadata()
        if not symbols_raw or len(symbols_raw) < 10:
            raise RuntimeError("No symbols fetched from screener/API; check API key, network, or provider limits.")
    except Exception as e:
        log_progress("Failed to fetch screener symbol metadata", {"error": str(e)})
        raise

    log_progress("Fetched raw symbols from screener feed", {"count": len(symbols_raw)})

    # ---- NORMALIZE all prices and market cap, filter out lastClose <= 0 ----
    symbols_normed = normalize_symbol_data(symbols_raw)

    blocklist = load_blocklist(blocklist_path)

    symbols_filtered = filter_symbols(
        symbols=symbols_normed,
        exchanges=exchanges,
        min_price=min_price,
        max_price=max_price,
        min_market_cap=min_cap,
        max_market_cap=max_cap,
        blocklist=blocklist,
        max_size=max_size
    )

    symbols_filtered.sort(key=lambda x: x["symbol"])

    # Integrity check: compare RAM with partial before writing
    try:
        # Load the partial (if exists)
        partial_path = resolve_universe_partial_path()
        with open(partial_path, "r", encoding="utf-8") as pf:
            partial = json.load(pf)
        partial_symbols = partial["symbols"]
        if symbols_filtered != partial_symbols:
            log_progress("INTEGRITY CHECK FAILED: RAM and partial JSON differ!", {
                "ram_count": len(symbols_filtered),
                "partial_count": len(partial_symbols)
            })
            raise RuntimeError("Integrity check failed: RAM and partial JSON differ.")
        else:
            log_progress("INTEGRITY CHECK PASSED: RAM matches partial JSON.", {
                "count": len(symbols_filtered)
            })
    except Exception as e:
        log_progress("Integrity check error (could not read partial or mismatch): proceeding with RAM.", {"error": str(e)})

    try:
        save_universe_cache(symbols_filtered, bot_identity=bot_identity)
        log_progress("Universe cache build complete", {"final_count": len(symbols_filtered)})
    except Exception as e:
        log_progress("Failed to write universe cache", {"error": str(e)})
        raise

    audit = {
        "build_time_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "total_symbols_fetched": len(symbols_raw),
        "total_symbols_final": len(symbols_filtered),
        "exchanges": exchanges,
        "blocklist_entries": len(blocklist),
        "cache_path": resolve_universe_cache_path(bot_identity),
    }
    log_progress("Universe build summary", audit)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_progress("Universe build failed and raised exception", {"error": str(e)})
        sys.exit(1)
