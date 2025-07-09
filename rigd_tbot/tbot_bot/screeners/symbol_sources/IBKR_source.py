# tbot_bot/screeners/symbol_sources/IBKR_source.py
# Loader for IBKR (paid/unlimited, symbol/price/metadata, API).
# 100% compliant with v046 staged universe/blocklist/adapter spec.

import requests
from typing import List, Dict

def load_ibkr_symbols(
    api_key: str,
    base_url: str,
    exchanges: list = None,
    username: str = "",
    password: str = ""
) -> List[Dict]:
    """
    Loads symbols and metadata from IBKR REST API.
    Filters to supported exchanges if provided.
    Returns list of dicts: {symbol, exchange, companyName}
    """
    syms = []
    auth = (username, password) if username and password else None
    target_exch = set(e.upper() for e in exchanges) if exchanges else {"NASDAQ", "NYSE"}
    for exch in target_exch:
        url = f"{base_url.rstrip('/')}/symbols?exchange={exch}&apikey={api_key}"
        try:
            r = requests.get(url, auth=auth, verify=False, timeout=30)
            if r.status_code != 200:
                continue
            for s in r.json().get("symbols", []):
                symbol = s.get("symbol", "").upper()
                name = s.get("name", "")
                syms.append({
                    "symbol": symbol,
                    "exchange": exch,
                    "companyName": name
                })
        except Exception:
            continue
    return syms
