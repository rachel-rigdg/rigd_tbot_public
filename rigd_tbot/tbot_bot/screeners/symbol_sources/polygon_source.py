# tbot_bot/screeners/symbol_sources/polygon_source.py
# Loader for Polygon API (free/paid, symbol/price/metadata, API key).
# 100% compliant with v046 staged universe/blocklist/adapter spec.

import requests
from typing import List, Dict

def load_polygon_symbols(api_key: str, exchanges: list = None) -> List[Dict]:
    """
    Loads symbols and metadata from Polygon.io API (supports free/paid).
    Filters to supported exchanges (NASDAQ, NYSE) if provided.
    Returns list of dicts: {symbol, exchange, companyName}
    """
    url = f"https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&apiKey={api_key}"
    syms = []
    page = 1
    target_exch = set(e.upper() for e in exchanges) if exchanges else {"NASDAQ", "NYSE"}
    while True:
        req_url = f"{url}&limit=1000&page={page}"
        r = requests.get(req_url)
        if r.status_code != 200:
            break
        data = r.json()
        tickers = data.get("results", [])
        for t in tickers:
            exch_code = t.get("primary_exchange")
            symbol = t.get("ticker", "").upper()
            name = t.get("name", "")
            if exch_code == "XNAS":
                exch = "NASDAQ"
            elif exch_code == "XNYS":
                exch = "NYSE"
            else:
                exch = exch_code or "US"
            if not exchanges or exch in target_exch:
                syms.append({
                    "symbol": symbol,
                    "exchange": exch,
                    "companyName": name
                })
        if not data.get("next_url"):
            break
        page += 1
    return syms
