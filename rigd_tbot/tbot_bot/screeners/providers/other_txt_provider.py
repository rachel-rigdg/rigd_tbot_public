# tbot_bot/screeners/providers/other_txt_provider.py
# Generic TXT provider adapter: loads symbols from TXT/CSV files (AMEX, OTC, custom lists, etc).
# No credentials required for file-based symbol fetch. Quotes via IBKR if needed.
# Fully self-contained and stateless per specification.

import csv
import os
from typing import List, Dict, Optional

# ---- Symbol Loader ----
def load_other_txt(path: str, exchange: str = "OTHER") -> List[Dict]:
    """
    Loads symbols from a TXT/CSV file with columns: Symbol, Security Name.
    Only includes valid symbols (non-empty, non-placeholder).
    Returns list of dicts: {symbol, exchange, companyName}
    """
    if not os.path.isfile(path):
        raise RuntimeError(f"[other_txt_provider] File not found: {path}")

    syms = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader((line for line in f if line.strip()), delimiter="|")
        for row in reader:
            symbol = row.get("Symbol", "").strip().upper()
            name = row.get("Security Name", "").strip()
            if not symbol or "Test Issue" in name or symbol.startswith("ZVZZT"):
                continue
            syms.append({
                "symbol": symbol,
                "exchange": exchange.upper(),
                "companyName": name
            })
    return syms

# ---- Quote Fetch (if needed, via IBKR) ----
from ib_insync import IB, Stock
from tbot_bot.support.secrets_manager import get_provider_credentials

def _make_ibkr_client() -> IB:
    """
    Loads IBKR credentials from the central secrets manager and returns an authenticated IB instance.
    """
    creds = get_provider_credentials("IBKR")
    if not creds:
        raise RuntimeError("[other_txt_provider] IBKR credentials not found in secrets_manager.")
    ibkr = IB()
    ibkr.connect(
        creds["BROKER_HOST"],
        int(creds["BROKER_PORT"]),
        clientId=int(creds.get("BROKER_CLIENT_ID", 1))
    )
    return ibkr

def fetch_other_quote_ibkr(symbol: str, exchange: str = "AMEX") -> Dict:
    """
    Fetches live quote data for a given symbol on the specified exchange from IBKR.
    Returns dict: {symbol, c, o, vwap}
    """
    ibkr_client = _make_ibkr_client()
    contract = Stock(symbol, exchange.upper(), "USD")
    ticker = ibkr_client.reqMktData(contract, "", False, False)
    ibkr_client.sleep(2)
    result = {
        "symbol": symbol,
        "c": float(getattr(ticker, 'last', 0) or 0),
        "o": float(getattr(ticker, 'open', 0) or 0),
        "vwap": float(getattr(ticker, 'vwap', 0) or 0)
    }
    ibkr_client.disconnect()
    return result

# Example usage for file-based symbol load:
# syms = load_other_txt("/path/to/amexlisted.txt", exchange="AMEX")
