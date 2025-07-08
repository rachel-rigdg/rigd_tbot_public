# tbot_bot/screeners/symbol_source_loader.py
# Unified loader for all symbol sources: nasdaqlisted.txt, otherexchanges.txt, Tradier, Polygon, etc.
# Normalizes and yields deduped symbol dicts for staged universe builds.
# 100% spec-compliant per Symbol Universe, Blocklist, and staged API fetch specification.

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

def load_tradier_symbols(api_key: str) -> List[Dict]:
    """
    Loads symbols from Tradier API (market symbol list, equity only).
    """
    import requests
    url = "https://api.tradier.com/v1/markets/symbols"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError("Tradier symbol fetch failed")
    syms = []
    symbols = r.json().get("symbols", {}).get("symbol", [])
    for s in symbols:
        if s.get("type") == "stock":
            syms.append({
                "symbol": s.get("symbol", "").upper(),
                "exchange": s.get("exchange", "US").upper(),
                "companyName": s.get("description", "")
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
    tradier_api_key: str = None,
    polygon_api_key: str = None
) -> List[Dict]:
    """
    Loads all symbol sources in priority order, dedupes, returns merged list.
    """
    symbols = []
    if nasdaq_path and os.path.exists(nasdaq_path):
        symbols += load_nasdaq_listed(nasdaq_path)
    if nyse_path and os.path.exists(nyse_path):
        symbols += load_nyse_listed(nyse_path)
    if tradier_api_key:
        symbols += load_tradier_symbols(tradier_api_key)
    if polygon_api_key:
        symbols += load_polygon_symbols(polygon_api_key)
    return dedupe_symbols(symbols)

if __name__ == "__main__":
    # Example CLI usage
    import argparse
    parser = argparse.ArgumentParser(description="Symbol source loader for universe build")
    parser.add_argument("--nasdaq", help="Path to nasdaqlisted.txt")
    parser.add_argument("--nyse", help="Path to NYSE/otherexchanges.txt")
    parser.add_argument("--tradier-key", help="Tradier API key")
    parser.add_argument("--polygon-key", help="Polygon API key")
    parser.add_argument("--out", help="Output JSON path", default="symbol_source_merged.json")
    args = parser.parse_args()
    syms = load_all_sources(
        nasdaq_path=args.nasdaq,
        nyse_path=args.nyse,
        tradier_api_key=args.tradier_key,
        polygon_api_key=args.polygon_key
    )
    print(f"Loaded {len(syms)} unique symbols from all sources")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(syms, f, indent=2)
