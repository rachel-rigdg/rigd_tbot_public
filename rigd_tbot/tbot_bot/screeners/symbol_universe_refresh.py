# tbot_bot/screeners/symbol_universe_refresh.py

import sys
import json
import logging
import time
from decimal import Decimal
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

UNFILTERED_PATH = "tbot_bot/output/screeners/symbol_universe.unfiltered.json"

LOG_PATH = resolve_universe_log_path()

def log_progress(msg: str, details: dict = None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")
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

def write_unfiltered(unfiltered_symbols):
    with open(UNFILTERED_PATH, "w", encoding="utf-8") as uf:
        json.dump({"symbols": unfiltered_symbols}, uf, indent=2)

def load_unfiltered():
    try:
        with open(UNFILTERED_PATH, "r", encoding="utf-8") as uf:
            data = json.load(uf)
            return data.get("symbols", [])
    except Exception:
        return []

def normalize_symbol_data(symbols: List[Dict]) -> List[Dict]:
    last_close_aliases = ["lastClose", "close", "last_price", "price"]
    market_cap_aliases = ["marketCap", "market_cap", "mktcap", "market_capitalization"]
    normed = []
    for s in symbols:
        lc = None
        mc = None
        for k in last_close_aliases:
            val = s.get(k, None)
            if val not in (None, '', 'None', 'null'):
                try:
                    lc = float(val)
                    break
                except Exception:
                    try:
                        lc = float(Decimal(str(val)))
                        break
                    except Exception:
                        lc = None
        for k in market_cap_aliases:
            val = s.get(k, None)
            if val not in (None, '', 'None', 'null'):
                try:
                    mc = float(val)
                    break
                except Exception:
                    try:
                        mc = float(Decimal(str(val)))
                        break
                    except Exception:
                        mc = None
        s["lastClose"] = lc
        s["marketCap"] = mc
        if lc is not None and mc is not None and float(lc) >= 1.0:
            normed.append(s)
    return normed

def dedupe_symbols(symbols: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for s in symbols:
        key = s.get("symbol")
        if key and key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped

def fetch_broker_symbol_metadata_crash_resilient(env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size):
    screener_secrets = get_screener_secrets()
    screener_name = (screener_secrets.get("SCREENER_NAME") or "FINNHUB").strip().upper()
    if screener_name == "FINNHUB":
        return fetch_finnhub_symbols_crash_resilient(
            screener_secrets, env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size
        )
    elif screener_name == "TRADIER":
        return fetch_tradier_symbols(screener_secrets, env)
    elif screener_name == "IBKR":
        return fetch_ibkr_symbols(screener_secrets, env)
    else:
        raise RuntimeError(f"Unsupported SCREENER_NAME: {screener_name}")

def fetch_finnhub_symbols_crash_resilient(secrets, env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size):
    import requests
    SCREENER_API_KEY = secrets.get("SCREENER_API_KEY") or secrets.get("SCREENER_TOKEN")
    SCREENER_URL = secrets.get("SCREENER_URL", "https://finnhub.io/api/v1/")
    SCREENER_USERNAME = secrets.get("SCREENER_USERNAME", "")
    SCREENER_PASSWORD = secrets.get("SCREENER_PASSWORD", "")
    UNIVERSE_SLEEP_TIME = float(env.get("UNIVERSE_SLEEP_TIME", 0.3))
    if not SCREENER_API_KEY:
        raise RuntimeError("SCREENER_API_KEY not set in screener secrets/config")
    unfiltered_symbols = load_unfiltered()
    filtered_symbols = []
    seen = set(s.get("symbol") for s in unfiltered_symbols)
    blockset = set(blocklist) if blocklist else set()
    for exch in exchanges:
        url = f"{SCREENER_URL.rstrip('/')}/stock/symbol?exchange={exch.strip()}&token={SCREENER_API_KEY}"
        auth = (SCREENER_USERNAME, SCREENER_PASSWORD) if SCREENER_USERNAME and SCREENER_PASSWORD else None
        r = requests.get(url, auth=auth)
        if r.status_code != 200:
            log_progress(f"Failed to fetch symbol list for exchange {exch}", {"status": r.status_code})
            continue
        for s in r.json():
            symbol = s.get("symbol")
            if symbol in seen:
                continue
            profile_url = f"{SCREENER_URL.rstrip('/')}/stock/profile2?symbol={symbol}&token={SCREENER_API_KEY}"
            profile = requests.get(profile_url, auth=auth)
            p = profile.json() if profile.status_code == 200 else {}
            time.sleep(UNIVERSE_SLEEP_TIME)
            quote_url = f"{SCREENER_URL.rstrip('/')}/quote?symbol={symbol}&token={SCREENER_API_KEY}"
            quote = requests.get(quote_url, auth=auth)
            q = quote.json() if quote.status_code == 200 else {}
            time.sleep(UNIVERSE_SLEEP_TIME)
            def safe_float(val):
                try:
                    if val is None or val == "" or (isinstance(val, str) and val.strip().lower() == "none"):
                        return None
                    return float(val)
                except Exception:
                    try:
                        return float(Decimal(str(val)))
                    except Exception:
                        return None
            obj = {
                "symbol": symbol,
                "exchange": exch.strip(),
                "lastClose": safe_float(q.get("pc")) or safe_float(q.get("c")),
                "marketCap": safe_float(p.get("marketCapitalization")),
                "name": p.get("name") or s.get("description") or "",
                "sector": p.get("finnhubIndustry") or "",
                "industry": "",
                "volume": q.get("v") or 0
            }
            unfiltered_symbols.append(obj)
            seen.add(symbol)
            write_unfiltered(dedupe_symbols(unfiltered_symbols))
            if len(unfiltered_symbols) % 100 == 0:
                log_progress(
                    f"Fetched {len(unfiltered_symbols)} symbols so far",
                    {"unfiltered_count": len(unfiltered_symbols)}
                )
            normed = normalize_symbol_data([obj])
            filtered = filter_symbols(
                normed,
                exchanges=exchanges,
                min_price=min_price,
                max_price=max_price,
                min_market_cap=min_cap,
                max_market_cap=max_cap,
                blocklist=blocklist,
                max_size=None
            )
            if filtered:
                filtered_symbols.extend(filtered)
                write_partial(dedupe_symbols(filtered_symbols))
                save_universe_cache(dedupe_symbols(filtered_symbols))
    write_unfiltered(dedupe_symbols(unfiltered_symbols))
    write_partial(dedupe_symbols(filtered_symbols))
    save_universe_cache(dedupe_symbols(filtered_symbols))
    _merge_and_dedupe_partials()
    return dedupe_symbols(filtered_symbols)

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
    return []

def _merge_and_dedupe_partials():
    try:
        with open(UNFILTERED_PATH, "r", encoding="utf-8") as uf:
            unfiltered = json.load(uf).get("symbols", [])
    except Exception:
        unfiltered = []
    partial_path = resolve_universe_partial_path()
    cache_path = resolve_universe_cache_path()
    try:
        with open(partial_path, "r", encoding="utf-8") as pf:
            partial = json.load(pf).get("symbols", [])
    except Exception:
        partial = []
    try:
        with open(cache_path, "r", encoding="utf-8") as cf:
            final = json.load(cf).get("symbols", [])
    except Exception:
        final = []
    merged = dedupe_symbols(partial + final)
    write_partial(merged)
    save_universe_cache(merged)

def refilter_from_unfiltered(env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size):
    unfiltered_symbols = load_unfiltered()
    normed = normalize_symbol_data(unfiltered_symbols)
    filtered = filter_symbols(
        normed,
        exchanges=exchanges,
        min_price=min_price,
        max_price=max_price,
        min_market_cap=min_cap,
        max_market_cap=max_cap,
        blocklist=blocklist,
        max_size=max_size
    )
    write_partial(dedupe_symbols(filtered))
    save_universe_cache(dedupe_symbols(filtered))
    _merge_and_dedupe_partials()
    return filtered

def disk_integrity_check_partial_vs_final():
    try:
        with open(resolve_universe_partial_path(), "r", encoding="utf-8") as pf:
            partial = json.load(pf).get("symbols", [])
    except Exception:
        partial = []
    try:
        with open(resolve_universe_cache_path(), "r", encoding="utf-8") as cf:
            final = json.load(cf).get("symbols", [])
    except Exception:
        final = []
    set_partial = set(s.get("symbol") for s in partial if s.get("symbol"))
    set_final = set(s.get("symbol") for s in final if s.get("symbol"))
    if set_partial != set_final or len(partial) != len(final):
        log_progress("DISK INTEGRITY CHECK FAILED: partial and final JSON differ!", {
            "partial_count": len(partial),
            "final_count": len(final),
            "partial_not_final": list(set_partial - set_final),
            "final_not_partial": list(set_final - set_partial),
        })
    else:
        log_progress("DISK INTEGRITY CHECK PASSED: partial matches final.", {
            "count": len(partial)
        })

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

    blocklist = load_blocklist(blocklist_path)

    try:
        symbols_filtered = fetch_broker_symbol_metadata_crash_resilient(
            env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size
        )
        if not symbols_filtered or len(symbols_filtered) < 10:
            raise RuntimeError("No symbols fetched from screener/API; check API key, network, or provider limits.")
    except Exception as e:
        log_progress("Failed to fetch screener symbol metadata", {"error": str(e)})
        raise

    log_progress("Fetched filtered symbols from screener feed", {"count": len(symbols_filtered)})

    symbols_filtered.sort(key=lambda x: x["symbol"])

    try:
        partial_path = resolve_universe_partial_path()
        write_partial(dedupe_symbols(symbols_filtered))
    except Exception as e:
        log_progress("Write partial failed", {"error": str(e)})

    try:
        save_universe_cache(dedupe_symbols(symbols_filtered), bot_identity=bot_identity)
        log_progress("Universe cache build complete", {"final_count": len(symbols_filtered)})
    except Exception as e:
        log_progress("Failed to write universe cache", {"error": str(e)})
        raise

    disk_integrity_check_partial_vs_final()

    audit = {
        "build_time_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "total_symbols_fetched": len(symbols_filtered),
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
