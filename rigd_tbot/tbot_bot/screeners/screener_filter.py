# tbot_bot/screeners/screener_filter.py
# Centralized, screener-agnostic symbol normalization and atomic filter for TradeBot v1.0.0+
# Implements robust field handling, blocklist-first, and returns (bool, reason) for atomic append logic.

import re
from decimal import Decimal
from typing import List, Dict, Optional, Tuple

MIC_TO_EXCHANGE = {
    "XNAS": "NASDAQ",
    "XNYS": "NYSE",
    "ARCX": "NYSE",
    "XASE": "AMEX",
    "OOTC": "OTC",
    "XNGS": "NASDAQ",
    "XBOS": "NASDAQ",
    "BATS": "BATS",
    "EDGA": "BATS",
    "EDGX": "BATS",
    "XPHL": "NASDAQ",
}

SYMBOL_KEYS         = ("symbol", "ticker", "displaySymbol")
EXCHANGE_KEYS       = ("exchange", "exch", "mic", "exchCode")
LASTCLOSE_KEYS      = ("lastClose", "close", "last_price", "price", "c", "pc")
MKTCAP_KEYS         = ("marketCap", "market_cap", "mktcap", "market_capitalization", "marketCapitalization")
NAME_KEYS           = ("name", "description", "companyName")
SECTOR_KEYS         = ("sector", "industry", "finnhubIndustry")
VOLUME_KEYS         = ("volume", "vol", "v")

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
    norm = {}
    for k in SYMBOL_KEYS:
        if k in raw and raw[k] not in (None, "", "None"):
            norm["symbol"] = str(raw[k]).upper().strip()
            break
    mic_val = None
    for k in EXCHANGE_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            mic_val = v
            break
    norm["exchange"] = mic_to_exchange(mic_val)
    for k in LASTCLOSE_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["lastClose"] = tofloat(v)
            break
    for k in MKTCAP_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["marketCap"] = tofloat(v)
            break
    for k in NAME_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["companyName"] = str(v).strip()
            break
    for k in SECTOR_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["sector"] = str(v).strip()
            break
    for k in VOLUME_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            try:
                norm["volume"] = int(v)
            except Exception:
                norm["volume"] = 0
            break
    # Copy all other unknown fields (but do not overwrite normalized keys)
    for k in raw:
        if k not in norm:
            norm[k] = raw[k]
    return norm

def normalize_symbols(symbols: List[Dict]) -> List[Dict]:
    return [normalize_symbol(s) for s in symbols]

def passes_filter(
    s: Dict,
    exchanges: List[str],
    min_price: float,
    max_price: float,
    min_market_cap: float,
    max_market_cap: float,
    blockset: Optional[set] = None,
    broker_obj=None
) -> Tuple[bool, str]:
    exch = s.get("exchange", "")
    sym = s.get("symbol", "")
    lc  = s.get("lastClose", None)
    mc  = s.get("marketCap", None)
    # Blocklist-first check
    if blockset and sym.upper() in blockset:
        return False, "blocklisted"
    # Exchange compliance
    if "US" in [e.upper() for e in exchanges]:
        valid_exchange = exch.upper() in ("NASDAQ", "NYSE", "AMEX", "BATS", "OTC")
    else:
        valid_exchange = exch and exch.upper() in [e.upper() for e in exchanges]
    if not (valid_exchange and sym):
        return False, "exchange"
    if lc is None or mc is None:
        return False, "missing_fields"
    if not (min_price <= lc <= max_price):
        return False, "price"
    if not (min_market_cap <= mc <= max_market_cap):
        return False, "market_cap"
    if broker_obj and hasattr(broker_obj, "is_symbol_tradable"):
        if not broker_obj.is_symbol_tradable(sym):
            return False, "not_tradable"
    return True, ""

def filter_symbols(
    symbols: List[Dict],
    exchanges: List[str],
    min_price: float,
    max_price: float,
    min_market_cap: float,
    max_market_cap: float,
    blocklist: Optional[List[str]] = None,
    max_size: Optional[int] = None,
    broker_obj=None
) -> List[Dict]:
    blockset = set(b.upper() for b in blocklist) if blocklist else set()
    normalized = normalize_symbols(symbols)
    filtered = [
        s for s in normalized
        if passes_filter(
            s,
            exchanges,
            min_price,
            max_price,
            min_market_cap,
            max_market_cap,
            blockset,
            broker_obj
        )[0]
    ]
    if max_size is not None and len(filtered) > max_size:
        filtered.sort(key=lambda x: x.get("marketCap", 0.0) or 0.0, reverse=True)
        filtered = filtered[:max_size]
    return filtered

def dedupe_symbols(symbols: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for s in symbols:
        key = s.get("symbol")
        if key and key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped
