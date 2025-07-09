# tbot_bot/screeners/symbol_universe_refresh.py

import sys
import json
import time
import os
from datetime import datetime, timezone
from typing import List, Dict
from tbot_bot.config.env_bot import load_env_bot_config
from tbot_bot.screeners.screener_utils import (
    save_universe_cache, load_blocklist, UniverseCacheError, get_screener_secrets
)
from tbot_bot.screeners.screener_filter import (
    normalize_symbols, filter_symbols, dedupe_symbols
)
from tbot_bot.broker.broker_api import get_active_broker
from tbot_bot.support.path_resolver import (
    resolve_universe_cache_path,
    resolve_universe_partial_path,
    resolve_universe_log_path,
    resolve_screener_blocklist_path
)
from tbot_bot.support.secrets_manager import get_screener_credentials_path

UNFILTERED_PATH = "tbot_bot/output/screeners/symbol_universe.unfiltered.json"
LOG_PATH = resolve_universe_log_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()

def screener_creds_exist():
    creds_path = get_screener_credentials_path()
    return os.path.exists(creds_path)

def log_progress(msg: str, details: dict = None):
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details:
        record += " | " + json.dumps(details)
    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        logf.write(record + "\n")

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

def append_to_blocklist(symbol, blocklist_path, reason="PRICE_BELOW_MIN"):
    try:
        now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
        with open(blocklist_path, "a", encoding="utf-8") as f:
            f.write(f"{symbol.upper()},{reason},{now}\n")
    except Exception:
        pass

def fetch_finnhub_symbols_staged(env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size, broker_obj=None):
    import requests
    screener_secrets = get_screener_secrets()
    FINNHUB_API_KEY = screener_secrets.get("FINNHUB_API_KEY") or screener_secrets.get("SCREENER_API_KEY") or screener_secrets.get("SCREENER_TOKEN")
    FINNHUB_URL = screener_secrets.get("FINNHUB_URL", "https://finnhub.io/api/v1/")
    FINNHUB_USERNAME = screener_secrets.get("FINNHUB_USERNAME", "")
    FINNHUB_PASSWORD = screener_secrets.get("FINNHUB_PASSWORD", "")
    UNIVERSE_SLEEP_TIME = float(env.get("UNIVERSE_SLEEP_TIME", 0.3))
    blocklist_path = BLOCKLIST_PATH
    if not FINNHUB_API_KEY:
        raise RuntimeError("FINNHUB_API_KEY not set in screener_api.json.enc")
    unfiltered_symbols = load_unfiltered()
    filtered_symbols = []
    seen = set(s.get("symbol") for s in unfiltered_symbols)
    blockset = set(line.strip().split(',')[0] for line in blocklist) if blocklist else set()
    for exch in exchanges:
        url = f"{FINNHUB_URL.rstrip('/')}/stock/symbol?exchange={exch.strip()}&token={FINNHUB_API_KEY}"
        auth = (FINNHUB_USERNAME, FINNHUB_PASSWORD) if FINNHUB_USERNAME and FINNHUB_PASSWORD else None
        r = requests.get(url, auth=auth)
        if r.status_code != 200:
            log_progress(f"Failed to fetch symbol list for exchange {exch}", {"status": r.status_code})
            continue
        for s in r.json():
            symbol = s.get("symbol")
            if symbol in seen or symbol.upper() in blockset:
                continue
            if symbol.upper() in blockset:
                continue
            quote_url = f"{FINNHUB_URL.rstrip('/')}/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            quote = requests.get(quote_url, auth=auth)
            q = quote.json() if quote.status_code == 200 else {}
            last_close = q.get("pc") or q.get("c")
            try:
                last_close = float(last_close)
            except Exception:
                last_close = None
            if last_close is None or last_close < min_price:
                append_to_blocklist(symbol, blocklist_path, reason="PRICE_BELOW_MIN")
                continue
            profile_url = f"{FINNHUB_URL.rstrip('/')}/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}"
            profile = requests.get(profile_url, auth=auth)
            p = profile.json() if profile.status_code == 200 else {}
            time.sleep(UNIVERSE_SLEEP_TIME)
            obj = {
                "symbol": symbol,
                "exchange": exch.strip(),
                "lastClose": last_close,
                "marketCap": p.get("marketCapitalization"),
                "name": p.get("name") or s.get("description") or "",
                "sector": p.get("finnhubIndustry") or "",
                "industry": "",
                "volume": q.get("v") or 0,
                "isFractional": broker_obj.is_symbol_fractional(symbol) if broker_obj else None
            }
            unfiltered_symbols.append(obj)
            seen.add(symbol)
            write_unfiltered(dedupe_symbols(unfiltered_symbols))
            if len(unfiltered_symbols) % 100 == 0:
                log_progress(
                    f"Fetched {len(unfiltered_symbols)} symbols so far",
                    {"unfiltered_count": len(unfiltered_symbols)}
                )
            normed = normalize_symbols([obj])
            filtered = filter_symbols(
                normed,
                exchanges=exchanges,
                min_price=min_price,
                max_price=max_price,
                min_market_cap=min_cap,
                max_market_cap=max_cap,
                blocklist=blocklist,
                max_size=None,
                broker_obj=broker_obj
            )
            if filtered:
                filtered_symbols.extend(filtered)
                write_partial(dedupe_symbols(filtered_symbols))
                save_universe_cache(dedupe_symbols(filtered_symbols))
            time.sleep(UNIVERSE_SLEEP_TIME)
    write_unfiltered(dedupe_symbols(unfiltered_symbols))
    write_partial(dedupe_symbols(filtered_symbols))
    save_universe_cache(dedupe_symbols(filtered_symbols))
    _merge_and_dedupe_partials()
    return dedupe_symbols(filtered_symbols)

def fetch_ibkr_symbols(secrets, env):
    import requests
    IBKR_API_KEY = secrets.get("IBKR_API_KEY")
    IBKR_BASE_URL = secrets.get("IBKR_BASE_URL", "https://localhost:5000/v1/api")
    IBKR_USERNAME = secrets.get("IBKR_USERNAME", "")
    IBKR_PASSWORD = secrets.get("IBKR_PASSWORD", "")
    UNIVERSE_SLEEP_TIME = float(env.get("UNIVERSE_SLEEP_TIME", 0.3))
    exchanges = [e.strip() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 5))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 2_000_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    blocklist_path = BLOCKLIST_PATH
    blocklist = []
    try:
        with open(blocklist_path, "r", encoding="utf-8") as bf:
            blocklist = bf.readlines()
    except Exception:
        blocklist = []
    blockset = set(line.strip().split(',')[0] for line in blocklist) if blocklist else set()
    unfiltered_symbols = load_unfiltered()
    filtered_symbols = []
    seen = set(s.get("symbol") for s in unfiltered_symbols)
    for exch in exchanges:
        url = f"{IBKR_BASE_URL.rstrip('/')}/symbols?exchange={exch.strip()}&apikey={IBKR_API_KEY}"
        auth = (IBKR_USERNAME, IBKR_PASSWORD) if IBKR_USERNAME and IBKR_PASSWORD else None
        r = requests.get(url, auth=auth, verify=False)
        if r.status_code != 200:
            log_progress(f"Failed to fetch IBKR symbols for {exch}", {"status": r.status_code})
            continue
        for s in r.json().get("symbols", []):
            symbol = s.get("symbol")
            if symbol in seen or symbol.upper() in blockset:
                continue
            quote_url = f"{IBKR_BASE_URL.rstrip('/')}/quote?symbol={symbol}&apikey={IBKR_API_KEY}"
            quote = requests.get(quote_url, auth=auth, verify=False)
            q = quote.json() if quote.status_code == 200 else {}
            last_close = q.get("lastClose") or q.get("close") or q.get("price")
            try:
                last_close = float(last_close)
            except Exception:
                last_close = None
            if last_close is None or last_close < min_price:
                append_to_blocklist(symbol, blocklist_path, reason="PRICE_BELOW_MIN")
                continue
            meta_url = f"{IBKR_BASE_URL.rstrip('/')}/meta?symbol={symbol}&apikey={IBKR_API_KEY}"
            meta = requests.get(meta_url, auth=auth, verify=False)
            p = meta.json() if meta.status_code == 200 else {}
            time.sleep(UNIVERSE_SLEEP_TIME)
            obj = {
                "symbol": symbol,
                "exchange": exch.strip(),
                "lastClose": last_close,
                "marketCap": p.get("marketCap"),
                "name": p.get("name") or s.get("name") or "",
                "sector": p.get("sector") or "",
                "industry": p.get("industry") or "",
                "volume": q.get("volume") or 0,
                "isFractional": p.get("isFractional") if p.get("isFractional") is not None else None
            }
            unfiltered_symbols.append(obj)
            seen.add(symbol)
            write_unfiltered(dedupe_symbols(unfiltered_symbols))
            if len(unfiltered_symbols) % 100 == 0:
                log_progress(
                    f"Fetched {len(unfiltered_symbols)} IBKR symbols so far",
                    {"unfiltered_count": len(unfiltered_symbols)}
                )
            normed = normalize_symbols([obj])
            filtered = filter_symbols(
                normed,
                exchanges=exchanges,
                min_price=min_price,
                max_price=max_price,
                min_market_cap=min_cap,
                max_market_cap=max_cap,
                blocklist=blocklist,
                max_size=None,
                broker_obj=None
            )
            if filtered:
                filtered_symbols.extend(filtered)
                write_partial(dedupe_symbols(filtered_symbols))
                save_universe_cache(dedupe_symbols(filtered_symbols))
            time.sleep(UNIVERSE_SLEEP_TIME)
    write_unfiltered(dedupe_symbols(unfiltered_symbols))
    write_partial(dedupe_symbols(filtered_symbols))
    save_universe_cache(dedupe_symbols(filtered_symbols))
    _merge_and_dedupe_partials()
    return dedupe_symbols(filtered_symbols)

def fetch_broker_symbol_metadata_crash_resilient(env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size):
    if not screener_creds_exist():
        raise RuntimeError("Screener credentials not configured. Please configure screener credentials in the UI before building the universe.")
    screener_secrets = get_screener_secrets()
    screener_name = (screener_secrets.get("SCREENER_NAME") or "FINNHUB").strip().upper()
    broker_obj = get_active_broker()
    if screener_name == "FINNHUB":
        return fetch_finnhub_symbols_staged(
            env, blocklist, exchanges, min_price, max_price, min_cap, max_cap, max_size, broker_obj
        )
    elif screener_name == "IBKR":
        return fetch_ibkr_symbols(screener_secrets, env)
    else:
        raise RuntimeError(f"Unsupported SCREENER_NAME: {screener_name}")

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
    normed = normalize_symbols(unfiltered_symbols)
    broker_obj = get_active_broker()
    filtered = filter_symbols(
        normed,
        exchanges=exchanges,
        min_price=min_price,
        max_price=max_price,
        min_market_cap=min_cap,
        max_market_cap=max_cap,
        blocklist=blocklist,
        max_size=max_size,
        broker_obj=broker_obj
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
    if not screener_creds_exist():
        print("Screener credentials not configured. Please configure screener credentials in the UI before building the universe.")
        sys.exit(2)
    env = load_env_bot_config()
    exchanges = [e.strip() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(",")]
    min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 5))
    max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
    min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 2_000_000_000))
    max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
    max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))
    blocklist_path = BLOCKLIST_PATH
    bot_identity = env.get("BOT_IDENTITY_STRING", None)

    log_progress("Universe build parameters", {
        "exchanges": exchanges,
        "price": [min_price, max_price],
        "cap": [min_cap, max_cap],
        "max_size": max_size,
        "blocklist": blocklist_path
    })

    try:
        with open(blocklist_path, "r", encoding="utf-8") as bf:
            blocklist = bf.readlines()
    except Exception:
        blocklist = []

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
