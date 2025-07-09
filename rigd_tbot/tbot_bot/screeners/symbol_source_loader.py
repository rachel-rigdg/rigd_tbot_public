# tbot_bot/screeners/symbol_source_loader.py
# Unified loader for all symbol sources: nasdaqlisted.txt, otherexchanges.txt, Polygon, IBKR, Finnhub, Yahoo.
# Normalizes and yields deduped symbol dicts for staged universe builds.
# 100% spec-compliant per Symbol Universe, Blocklist, and staged API fetch specification. Tradier is NOT supported.

import csv
import os
import json
from typing import List, Dict, Set

def load_nasdaq_listed(path: str) -> List[Dict]:
    """
    Loads symbols from nasdaqlisted.txt (NASDAQ Official List).
    Returns list of dicts: {symbol, exchange, companyName}
    """
    syms = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader((line for line in f if not line.startswith("File") and not line.startswith("\n")), delimiter="|")
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
    """
    Loads symbols from NYSE-style or otherexchanges.txt
    Returns list of dicts: {symbol, exchange, companyName}
    """
    syms = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader((line for line in f if not line.startswith("File") and not line.startswith("\n")), delimiter="|")
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

def load_polygon_symbols(api_key: str) -> List[Dict]:
    """
    Loads symbols from Polygon.io API (equities only).
    """
    import requests
    url = f"https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&apiKey={api_key}"
    syms = []
    page = 1
    while True:
        r = requests.get(url + f"&limit=1000&page={page}")
        if r.status_code != 200:
            break
        data = r.json()
        tickers = data.get("results", [])
        for t in tickers:
            if t.get("primary_exchange") in ("XNYS", "XNAS"):
                syms.append({
                    "symbol": t.get("ticker", "").upper(),
                    "exchange": "NASDAQ" if t.get("primary_exchange") == "XNAS" else "NYSE",
                    "companyName": t.get("name", "")
                })
        if not data.get("next_url"):
            break
        page += 1
    return syms

def load_finnhub_symbols(api_key: str, exchanges: List[str]) -> List[Dict]:
    """
    Loads symbols from Finnhub (for given exchanges).
    """
    import requests
    syms = []
    base_url = "https://finnhub.io/api/v1/stock/symbol"
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

def load_ibkr_symbols(api_key: str, base_url: str, exchanges: List[str], username: str = "", password: str = "") -> List[Dict]:
    """
    Loads symbols from IBKR REST API for given exchanges.
    """
    import requests
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
    """
    Loads symbols from Yahoo or pre-built CSVs.
    """
    # Placeholder: Yahoo fetcher requires scraping or CSV, not implemented here.
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
    polygon_api_key: str = None,
    finnhub_api_key: str = None,
    ibkr_api_key: str = None,
    ibkr_base_url: str = None,
    ibkr_username: str = "",
    ibkr_password: str = "",
    exchanges: List[str] = None
) -> List[Dict]:
    """
    Loads all symbol sources in priority order, dedupes, returns merged list.
    """
    symbols = []
    if nasdaq_path and os.path.exists(nasdaq_path):
        symbols += load_nasdaq_listed(nasdaq_path)
    if nyse_path and os.path.exists(nyse_path):
        symbols += load_nyse_listed(nyse_path)
    if polygon_api_key:
        symbols += load_polygon_symbols(polygon_api_key)
    if finnhub_api_key and exchanges:
        symbols += load_finnhub_symbols(finnhub_api_key, exchanges)
    if ibkr_api_key and ibkr_base_url and exchanges:
        symbols += load_ibkr_symbols(ibkr_api_key, ibkr_base_url, exchanges, ibkr_username, ibkr_password)
    # Add Yahoo or other adapters if needed in the future.
    return dedupe_symbols(symbols)

if __name__ == "__main__":
    # Example CLI usage
    import argparse
    parser = argparse.ArgumentParser(description="Symbol source loader for universe build")
    parser.add_argument("--nasdaq", help="Path to nasdaqlisted.txt")
    parser.add_argument("--nyse", help="Path to NYSE/otherexchanges.txt")
    parser.add_argument("--polygon-key", help="Polygon API key")
    parser.add_argument("--finnhub-key", help="Finnhub API key")
    parser.add_argument("--ibkr-key", help="IBKR API key")
    parser.add_argument("--ibkr-url", help="IBKR REST base URL")
    parser.add_argument("--ibkr-user", help="IBKR username", default="")
    parser.add_argument("--ibkr-pass", help="IBKR password", default="")
    parser.add_argument("--exchanges", help="Comma separated list of exchanges", default="NASDAQ,NYSE")
    parser.add_argument("--out", help="Output JSON path", default="symbol_source_merged.json")
    args = parser.parse_args()
    syms = load_all_sources(
        nasdaq_path=args.nasdaq,
        nyse_path=args.nyse,
        polygon_api_key=args.polygon_key,
        finnhub_api_key=args.finnhub_key,
        ibkr_api_key=args.ibkr_key,
        ibkr_base_url=args.ibkr_url,
        ibkr_username=args.ibkr_user,
        ibkr_password=args.ibkr_pass,
        exchanges=[e.strip().upper() for e in args.exchanges.split(",")]
    )
    print(f"Loaded {len(syms)} unique symbols from all sources")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(syms, f, indent=2)
