# tbot_bot/screeners/screener_filter.py
# Centralized, screener-agnostic symbol normalization and atomic filter for TradeBot v1.0.0+
# Filtering logic now supports exchange whitelist via SCREENER_UNIVERSE_EXCHANGES.
# Enhanced: robust normalization, numeric/format handling, and debug logging for missing fields.
# MARKET CAP NORMALIZED TO USD (ALL VALUES FROM FEED ARE TREATED AS MILLIONS)
# Fully compliant: handles all configured filter fields, no missing criteria.

import re
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from copy import deepcopy  # (surgical) for auto-ranging rescale retries

SYMBOL_KEYS         = ("symbol", "ticker", "displaySymbol")
LASTCLOSE_KEYS      = ("lastClose", "close", "last_price", "price", "c", "pc")
MKTCAP_KEYS         = ("marketCap", "market_cap", "mktcap", "market_capitalization", "marketCapitalization")
NAME_KEYS           = ("name", "description", "companyName")
SECTOR_KEYS         = ("sector", "industry", "finnhubIndustry")
VOLUME_KEYS         = ("volume", "vol", "v")
EXCHANGE_KEYS       = ("exchange", "mic")

def tofloat(val):
    # Defensive, robust conversion: handles commas, "M"/"B" suffix, string/None, zero
    if val is None:
        return None
    if isinstance(val, str):
        v = val.replace(",", "").strip().upper()
        if v in ("", "NONE", "NULL", "N/A"):
            return None
        mult = 1.0
        if v.endswith("M"):
            mult = 1_000_000
            v = v[:-1]
        elif v.endswith("B"):
            mult = 1_000_000_000
            v = v[:-1]
        try:
            return float(v) * mult
        except Exception:
            try:
                return float(Decimal(str(v))) * mult
            except Exception:
                return None
    try:
        return float(val)
    except Exception:
        try:
            return float(Decimal(str(val)))
        except Exception:
            return None

def normalize_market_cap(val):
    try:
        cap = tofloat(val)
        # Finnhub/your feed: marketCap is in MILLIONS -- multiply by 1,000,000
        return cap * 1_000_000 if cap is not None else None
    except Exception:
        return None

def normalize_symbol(raw: Dict) -> Dict:
    norm = {}
    debug_missing = []
    # Symbol normalization
    for k in SYMBOL_KEYS:
        if k in raw and raw[k] not in (None, "", "None"):
            norm["symbol"] = str(raw[k]).upper().strip()
            break
    # LastClose normalization
    found_lc = False
    for k in LASTCLOSE_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["lastClose"] = tofloat(v)
            found_lc = True
            break
    if not found_lc:
        debug_missing.append("lastClose")
    # MarketCap normalization (robust)
    found_mc = False
    for k in MKTCAP_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["marketCap"] = normalize_market_cap(v)
            found_mc = True
            break
    if not found_mc:
        debug_missing.append("marketCap")
    # Name normalization
    for k in NAME_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["companyName"] = str(v).strip()
            break
    # Sector normalization
    for k in SECTOR_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["sector"] = str(v).strip()
            break
    # Volume normalization
    for k in VOLUME_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            try:
                norm["volume"] = int(str(v).replace(",", ""))
            except Exception:
                norm["volume"] = 0
            break
    # Exchange normalization
    for k in EXCHANGE_KEYS:
        v = raw.get(k)
        if v not in (None, "", "None"):
            norm["exchange"] = str(v).upper().strip()
            break
    # Copy all other unknown fields (keep extra fields for info)
    for k in raw:
        if k not in norm:
            norm[k] = raw[k]
    # Debug log missing/invalid critical fields
    if debug_missing:
        print(f"[DEBUG] normalize_symbol: {norm.get('symbol','')} missing fields: {','.join(debug_missing)} in raw: {list(raw.keys())}")
    return norm

def normalize_symbols(symbols: List[Dict]) -> List[Dict]:
    out = []
    for s in symbols:
        try:
            out.append(normalize_symbol(s))
        except Exception as e:
            print(f"[DEBUG] normalize_symbols error: {e} for symbol: {s.get('symbol', '')}")
    return out

def passes_filter(
    s: Dict,
    min_price: float,
    max_price: float,
    min_market_cap: float,
    max_market_cap: float,
    allowed_exchanges: Optional[List[str]] = None,
    broker_obj=None
) -> Tuple[bool, str]:
    sym = s.get("symbol", "")
    lc  = s.get("lastClose", None)
    mc  = s.get("marketCap", None)
    exch = s.get("exchange", "").upper()
    # Explicit logging for skip reasons
    if not sym:
        print(f"[DEBUG] passes_filter: missing_symbol for {s}")
        return False, "missing_symbol"
    if lc is None or mc is None:
        print(f"[DEBUG] passes_filter: missing_fields for {sym} (lastClose: {lc}, marketCap: {mc})")
        return False, "missing_fields"
    if not (min_price <= lc <= max_price):
        print(f"[DEBUG] passes_filter: price out of range for {sym} (lastClose: {lc}, min: {min_price}, max: {max_price})")
        return False, "price"
    if not (min_market_cap <= mc <= max_market_cap):
        print(f"[DEBUG] passes_filter: marketCap out of range for {sym} (marketCap: {mc}, min: {min_market_cap}, max: {max_market_cap})")
        return False, "market_cap"
    if allowed_exchanges is not None and len(allowed_exchanges) > 0:
        if "*" not in allowed_exchanges:
            if exch not in allowed_exchanges:
                print(f"[DEBUG] passes_filter: exchange {exch} not in allowed_exchanges for {sym}")
                return False, "exchange"
    if broker_obj and hasattr(broker_obj, "is_symbol_tradable"):
        if not broker_obj.is_symbol_tradable(sym):
            print(f"[DEBUG] passes_filter: not_tradable for {sym}")
            return False, "not_tradable"
    return True, ""

# --- (surgical) helper for auto-ranging price rescaling ---
def _rescale_prices(records: List[Dict], factor: float) -> List[Dict]:
    """Return a deep-copied list with obvious price-like fields multiplied by factor.
    Market cap is intentionally NOT rescaled (already normalized)."""
    price_like = ("lastClose", "price", "c", "pc", "close", "last_price", "open", "o", "vwap")
    out = []
    for r in records:
        rr = deepcopy(r)
        for k in price_like:
            if k in rr and rr[k] not in (None, "", "None"):
                try:
                    rr[k] = tofloat(rr[k]) * factor
                except Exception:
                    # keep original if conversion fails
                    pass
        out.append(rr)
    return out

def filter_symbols(
    symbols: List[Dict],
    min_price: float,
    max_price: float,
    min_market_cap: float,
    max_market_cap: float,
    allowed_exchanges: Optional[List[str]] = None,
    max_size: Optional[int] = None,
    broker_obj=None
) -> List[Dict]:
    normalized = normalize_symbols(symbols)

    def _run(records: List[Dict]) -> List[Dict]:
        acc = []
        for s in records:
            passed, reason = passes_filter(
                s,
                min_price,
                max_price,
                min_market_cap,
                max_market_cap,
                allowed_exchanges,
                broker_obj
            )
            if not passed:
                print(f"[DEBUG] filter_symbols: symbol {s.get('symbol', '')} skipped, reason: {reason}")
            if passed:
                acc.append(s)
        return acc

    # First pass (original behavior)
    filtered = _run(normalized)

    # --- (surgical) AUTO-RANGING if too few symbols (classic cents/$ or 100x feed issues) ---
    MIN_OK = 5 if max_size is None else min(max_size, 5)
    if len(filtered) < MIN_OK:
        # Try cents->dollars
        attempt = _run(_rescale_prices(normalized, 0.01))
        if len(attempt) > len(filtered):
            print("[AUTO-SCALE] Recovered with price_scale=0.01 (cents->dollars).")
            filtered = attempt

        # Try dollars->cents
        if len(filtered) < MIN_OK:
            attempt = _run(_rescale_prices(normalized, 100.0))
            if len(attempt) > len(filtered):
                print("[AUTO-SCALE] Recovered with price_scale=100.0 (dollars->cents).")
                filtered = attempt

        # Try off-by-10 errors (rare but seen)
        if len(filtered) < MIN_OK:
            for factor in (0.1, 10.0):
                attempt = _run(_rescale_prices(normalized, factor))
                if len(attempt) > len(filtered):
                    print(f"[AUTO-SCALE] Recovered with price_scale={factor}.")
                    filtered = attempt
                    break

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
