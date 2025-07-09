# tbot_bot/screeners/symbol_sources/yahoo_source.py
# Loader for Yahoo Finance (free/delayed prices, metadata)
# 100% compliant with staged universe/blocklist/adapter spec.

import csv
from typing import List, Dict

def load_yahoo_csv(path: str) -> List[Dict]:
    """
    Loads symbols and metadata from Yahoo-exported CSV (or compatible).
    Only includes equities with valid symbol and name.
    Returns list of dicts: {symbol, exchange, companyName, sector, industry}
    """
    syms = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("Symbol")
            name = row.get("Name") or row.get("Company Name") or ""
            exch = row.get("Exchange", "US")
            sector = row.get("Sector", "")
            industry = row.get("Industry", "")
            if symbol and name and "Test Issue" not in name:
                syms.append({
                    "symbol": symbol.strip().upper(),
                    "exchange": exch.strip().upper() if exch else "US",
                    "companyName": name.strip(),
                    "sector": sector.strip(),
                    "industry": industry.strip()
                })
    return syms

# For full API support, a separate Yahoo API fetcher (web-scraping or yfinance) should be implemented.
# For universe builds, only static/daily CSV files or yfinance dumps should be used to avoid quota/ban.
