# tbot_bot/screeners/screener_filter.py
# Centralized, screener-agnostic symbol normalization and filtering for TradeBot v1.0.0
# 100% spec-compliant: robust field alias handling, MIC/exchange mapping, type safety, blocklist, and cap/price gating.

import re
from decimal import Decimal
from typing import List, Dict, Optional

# Map MIC codes to canonical exchange names (expand as needed)
MIC_TO_EXCHANGE = {
    "XNAS": "NASDAQ",
    "XNYS": "NYSE",
    "ARCX": "NYSE",    # NYSE ARCA
    "XASE": "AMEX",
    "OOTC": "OTC",
    "XNGS": "NASDAQ",
    "XBOS": "NASDAQ",
    "BATS": "BATS",
    "EDGA": "BATS",
    "EDGX": "BATS",
    "XPHL": "NASDAQ",
    # add more as needed
}

# Canonical filter field aliases
SYMBOL_KEYS      = ("symbol", "ticker", "displaySymbol")
EXCHANGE_KEYS    = ("exchange", "exch", "mic", "exchCode")
LASTCLOSE_KEYS   = ("lastClose", "close", "last_price", "price")
MKTCAP_KEYS      = ("marketCap", "market_cap", "mktcap", "market_capitalization")
NAME_KEYS        = ("name", "description", "companyName")
SECTOR_KEYS      = ("sector", "industry", "finnhubIndustry")
VOLUME_KEYS      = ("volume", "vol")

def mic_to_exchange(mic: Optional[str]) -> Optional[str]:
    mic = str(mic).upper().strip() if mic else ""
    return MIC_TO_EXCHANGE.get(mic, mic) if mic else None

def tofloat(val):
    try:
        if val is None or val == "" or (isinstance(val, str) and val.strip().lower() == "none"):
            return None
        return float(val)
    except Exception:
        try:
            return float(Decimal(str(val)))
        except Exception:
            return None

def normalize_symbol(raw: Dict) -> Dict:
    # Robustly normalize all fields to canonical TradeBot format
    norm = {}
    # Symbol
    for k in SYMBOL_KEYS:
        if k in raw and raw[k] not in (None, "", "None"):
            norm["symbol"] = str(raw[k]).upper().strip()
            break
    # Exchange/MIC
    mic_val = None
    for k in EXCHANGE_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            mic_val = v
            break
    norm["exchange"] = mic_to_exchange(mic_val)
    # Last Close
    for k in LASTCLOSE_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["lastClose"] = tofloat(v)
            break
    # Market Cap
    for k in MKTCAP_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["marketCap"] = tofloat(v)
            break
    # Name/Description
    for k in NAME_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["companyName"] = str(v).strip()
            break
    # Sector
    for k in SECTOR_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["sector"] = str(v).strip()
            break
    # Volume
    for k in VOLUME_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            try:
                norm["volume"] = int(v)
            except Exception:
                norm["volume"] = 0
            break
    # Preserve all other fields for downstream use
    for k in raw:
        if k not in norm:
            norm[k] = raw[k]
    return norm

def normalize_symbols(symbols: List[Dict]) -> List[Dict]:
    return [normalize_symbol(s) for s in symbols]

def filter_symbol(
    s: Dict,
    exchanges: List[str],
    min_price: float,
    max_price: float,
    min_market_cap: float,
    max_market_cap: float,
    blockset: Optional[set] = None
) -> bool:
    # All gating is on normalized fields
    exch = s.get("exchange", "")
    sym = s.get("symbol", "")
    lc  = s.get("lastClose", None)
    mc  = s.get("marketCap", None)
    # Accept "US" as any US major exchange if needed
    if "US" in [e.upper() for e in exchanges]:
        valid_exchange = exch.upper() in ("NASDAQ", "NYSE", "AMEX", "BATS", "OTC")
    else:
        valid_exchange = exch and exch.upper() in [e.upper() for e in exchanges]
    if not (valid_exchange and sym):
        return False
    if blockset and sym.upper() in blockset:
        return False
    if lc is None or mc is None:
        return False
    if not (min_price <= lc < max_price):
        return False
    if not (min_market_cap <= mc <= max_market_cap):
        return False
    return True

def filter_symbols(
    symbols: List[Dict],
    exchanges: List[str],
    min_price: float,
    max_price: float,
    min_market_cap: float,
    max_market_cap: float,
    blocklist: Optional[List[str]] = None,
    max_size: Optional[int] = None
) -> List[Dict]:
    blockset = set(b.upper() for b in blocklist) if blocklist else set()
    normalized = normalize_symbols(symbols)
    filtered = [
        s for s in normalized
        if filter_symbol(
            s,
            exchanges,
            min_price,
            max_price,
            min_market_cap,
            max_market_cap,
            blockset
        )
    ]
    if max_size is not None and len(filtered) > max_size:
        filtered.sort(key=lambda x: x.get("marketCap", 0.0) or 0.0, reverse=True)
        filtered = filtered[:max_size]
    return filtered
