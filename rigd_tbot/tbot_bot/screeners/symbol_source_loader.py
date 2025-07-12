# tbot_bot/screeners/symbol_source_loader.py
# 100% compliant: Always uses universe screener provider with UNIVERSE_ENABLED == "true" (get_universe_screener_secrets) for API keys/URLs.
# No hardcoded API keys; dynamic provider config only.

import csv
import os
import json
from typing import List, Dict

from tbot_bot.screeners.screener_utils import get_universe_screener_secrets

def load_nasdaq_listed(path: str) -> List[Dict]:
    syms = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(
            (line for line in f if not line.startswith("File") and not line.startswith("\n")),
            delimiter="|"
        )
        for row in reader:
            symbol = row.get("Symbol")
            name = row.get("Security Name", "")
            if symbol and "Test Issue" not in name:
                syms.append({
                    "symbol": symbol.strip().upper(),
                    "exchange": "NASDAQ",
                    "companyName": name.strip()
                })
    return syms

def load_nyse_listed(path: str) -> List[Dict]:
    syms = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(
            (line for line in f if not line.startswith("File") and not line.startswith("\n")),
            delimiter="|"
        )
        for row in reader:
            symbol = row.get("ACT Symbol") or row.get("Symbol")
            exch = row.get("Exchange", "NYSE")
            name = row.get("Security Name", "")
            if symbol and "Test Issue" not in name:
                syms.append({
                    "symbol": symbol.strip().upper(),
                    "exchange": exch.strip().upper() if exch else "NYSE",
                    "companyName": name.strip()
                })
    return syms

def load_polygon_symbols(provider_cfg: dict) -> List[Dict]:
    import requests
    api_key = provider_cfg.get("SCREENER_API_KEY") or provider_cfg.get("SCREENER_TOKEN")
    url = f"https://api.polygon.io/v3/reference/tickers"
    params = {
        "market": "stocks",
        "active": "true",
        "apiKey": api_key,
        "limit": 1000,
        "order": "asc"
    }
    syms = []
    next_url = url
    while next_url:
        resp = requests.get(next_url, params=params if next_url == url else None)
        if resp.status_code != 200:
            break
        data = resp.json()
        for t in data.get("results", []):
            exch_code = t.get("primary_exchange")
            symbol = t.get("ticker", "").upper()
            name = t.get("name", "")
            if exch_code == "XNAS":
                exch = "NASDAQ"
            elif exch_code == "XNYS":
                exch = "NYSE"
            else:
                exch = exch_code or "US"
            if exch in ("NASDAQ", "NYSE"):
                syms.append({
                    "symbol": symbol,
                    "exchange": exch,
                    "companyName": name
                })
        next_url = data.get("next_url")
        params = None  # Only pass params on first call
    return syms

def load_finnhub_symbols(provider_cfg: dict, exchanges: List[str]) -> List[Dict]:
    import requests
    api_key = provider_cfg.get("SCREENER_API_KEY") or provider_cfg.get("SCREENER_TOKEN")
    base_url = provider_cfg.get("SCREENER_URL", "https://finnhub.io/api/v1/stock/symbol")
    syms = []
    for exch in exchanges:
        url = f"{base_url}?exchange={exch.strip()}&token={api_key}"
        r = requests.get(url)
        if r.status_code != 200:
            continue
        for s in r.json():
            syms.append({
                "symbol": s.get("symbol", "").upper(),
                "exchange": exch.strip().upper(),
                "companyName": s.get("description", "")
            })
    return syms

def load_ibkr_symbols(provider_cfg: dict, exchanges: List[str]) -> List[Dict]:
    import requests
    api_key = provider_cfg.get("SCREENER_API_KEY") or provider_cfg.get("SCREENER_TOKEN")
    base_url = provider_cfg.get("SCREENER_URL", "https://localhost:5000/v1/api")
    username = provider_cfg.get("SCREENER_USERNAME", "")
    password = provider_cfg.get("SCREENER_PASSWORD", "")
    syms = []
    auth = (username, password) if username and password else None
    for exch in exchanges:
        url = f"{base_url.rstrip('/')}/symbols?exchange={exch.strip()}&apikey={api_key}"
        r = requests.get(url, auth=auth, verify=False)
        if r.status_code != 200:
            continue
        for s in r.json().get("symbols", []):
            syms.append({
                "symbol": s.get("symbol", "").upper(),
                "exchange": exch.strip().upper(),
                "companyName": s.get("name", "")
            })
    return syms

def load_yahoo_symbols() -> List[Dict]:
    # Placeholder for future Yahoo provider integration; currently no CSV/FTP usage.
    return []

def dedupe_symbols(symbols: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for s in symbols:
        key = s.get("symbol")
        if key and key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped

def load_all_sources(
    nasdaq_path: str = None,
    nyse_path: str = None,
    polygon: bool = False,
    finnhub: bool = False,
    ibkr: bool = False,
    exchanges: List[str] = None
) -> List[Dict]:
    """
    Loads all symbol sources in priority order, dedupes, returns merged list.
    Provider config always loaded via get_universe_screener_secrets().
    """
    symbols = []
    provider_cfg = get_universe_screener_secrets()
    if nasdaq_path and os.path.exists(nasdaq_path):
        symbols += load_nasdaq_listed(nasdaq_path)
    if nyse_path and os.path.exists(nyse_path):
        symbols += load_nyse_listed(nyse_path)
    if polygon:
        symbols += load_polygon_symbols(provider_cfg)
    if finnhub and exchanges:
        symbols += load_finnhub_symbols(provider_cfg, exchanges)
    if ibkr and exchanges:
        symbols += load_ibkr_symbols(provider_cfg, exchanges)
    # Yahoo provider is handled via dedicated adapter; no CSV/FTP loading here.
    return dedupe_symbols(symbols)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Symbol source loader for universe build")
    parser.add_argument("--nasdaq", help="Path to nasdaqlisted.txt")
    parser.add_argument("--nyse", help="Path to NYSE/otherexchanges.txt")
    parser.add_argument("--polygon", action="store_true", help="Enable Polygon API source")
    parser.add_argument("--finnhub", action="store_true", help="Enable Finnhub API source")
    parser.add_argument("--ibkr", action="store_true", help="Enable IBKR API source")
    parser.add_argument("--exchanges", help="Comma separated list of exchanges", default="NASDAQ,NYSE")
    parser.add_argument("--out", help="Output JSON path", default="symbol_source_merged.json")
    args = parser.parse_args()
    syms = load_all_sources(
        nasdaq_path=args.nasdaq,
        nyse_path=args.nyse,
        polygon=args.polygon,
        finnhub=args.finnhub,
        ibkr=args.ibkr,
        exchanges=[e.strip().upper() for e in args.exchanges.split(",")]
    )
    print(f"Loaded {len(syms)} unique symbols from all sources")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(syms, f, indent=2)
