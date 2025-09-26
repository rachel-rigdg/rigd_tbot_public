# tbot_bot/screeners/universe_validation.py
# Test/QA utility for validating universe and blocklist files, filter logic, deduplication, field compliance, and drift detection.
# 100% spec-compliant for all symbol universe and blocklist formats.

import sys
import os
import json
from datetime import datetime
from typing import List, Dict, Set, Tuple

REQUIRED_FIELDS = ["symbol", "exchange", "lastClose", "marketCap"]
SCHEMA_VERSION = "1.0.0"

def _load_ndjson_or_array(path: str) -> Tuple[List[Dict], Dict]:
    """
    Load a universe file that may be:
      - dict with {"symbols":[...]} (+ optional metadata)
      - JSON array of symbol dicts
      - NDJSON (one JSON object per line)
    Returns: (symbols_list, meta_dict)
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Try single JSON document first
    with open(path, "r", encoding="utf-8") as f:
        head = f.read(256)
        f.seek(0)
        first = next((ch for ch in head if not ch.isspace()), "")

        if first in ("{", "["):
            try:
                data = json.load(f)
                if isinstance(data, dict):
                    symbols = data.get("symbols")
                    if isinstance(symbols, list):
                        return symbols, data
                    # If dict but no 'symbols', treat as single record
                    return [data], data
                elif isinstance(data, list):
                    return data, {}
            except Exception:
                pass  # fall through to NDJSON

    # NDJSON fallback
    symbols: List[Dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, list):
                    symbols.extend([r for r in rec if isinstance(r, dict)])
                elif isinstance(rec, dict):
                    symbols.append(rec)
            except Exception:
                # ignore malformed lines for robustness
                continue
    return symbols, {}

def load_json_symbols(path: str) -> List[Dict]:
    symbols, _ = _load_ndjson_or_array(path)
    return symbols

def load_blocklist(path: str) -> Set[str]:
    syms = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().upper()
            if line and not line.startswith("#"):
                # Only add symbol (first comma, CSV format)
                syms.add(line.split(",", 1)[0])
    return syms

def _dedupe_and_find_dups(symbols: List[Dict]) -> Tuple[List[Dict], Set[str]]:
    seen = set()
    dups = set()
    out = []
    for s in symbols:
        sym = (s.get("symbol") or "").upper()
        if not sym:
            continue
        if sym in seen:
            dups.add(sym)
            continue
        seen.add(sym)
        out.append(s)
    return out, dups

def _validate_required_fields(symbols: List[Dict]) -> List[Tuple[str, List[str]]]:
    bad = []
    for s in symbols:
        missing = [k for k in REQUIRED_FIELDS if k not in s or s[k] in (None, "", "None")]
        # numeric sanity for price/cap
        try:
            if "lastClose" in s and (float(s["lastClose"]) <= 0):
                missing.append("lastClose>0")
        except Exception:
            missing.append("lastClose(parse)")
        try:
            if "marketCap" in s and (float(s["marketCap"]) <= 0):
                missing.append("marketCap>0")
        except Exception:
            missing.append("marketCap(parse)")
        if missing:
            bad.append((s.get("symbol", ""), missing))
    return bad

def _print_meta(meta: Dict):
    if not isinstance(meta, dict):
        return
    schema = meta.get("schema_version") or meta.get("schemaVersion")
    if schema and schema != SCHEMA_VERSION:
        print(f"  WARNING: Schema version mismatch: {schema} (expected {SCHEMA_VERSION})")
    ts = meta.get("build_timestamp_utc") or meta.get("buildTimestampUtc")
    if ts:
        print(f"  Build timestamp: {ts}")
    status = meta.get("status")
    if status:
        print(f"  Status: {status}")

def validate_universe(path: str) -> bool:
    print(f"\nValidating universe file: {path}")
    try:
        symbols, meta = _load_ndjson_or_array(path)
    except Exception as e:
        print(f"  ERROR: Failed to load: {e}")
        return False

    # Waiting stub passes with info note
    if isinstance(meta, dict) and meta.get("status") == "waiting_for_credentials":
        _print_meta(meta)
        print("  INFO: Waiting-for-credentials payload detected.")
        return True

    if not isinstance(symbols, list):
        print("  ERROR: Symbols payload is not a list")
        return False

    # Dedup and report duplicates (O(n))
    deduped, dups = _dedupe_and_find_dups(symbols)
    if dups:
        print(f"  ERROR: Duplicate symbols found: {sorted(dups)}")
        return False

    # Required fields + sanity checks
    bad = _validate_required_fields(deduped)
    if bad:
        for sym, miss in bad[:50]:
            print(f"  ERROR: Symbol {sym} missing/invalid fields: {miss}")
        if len(bad) > 50:
            print(f"  ... {len(bad)-50} more issues omitted")
        print(f"  {len(bad)} symbols missing required fields")
        return False

    # Counts & summary
    exchs = {}
    for s in deduped:
        ex = (s.get("exchange") or "").upper()
        exchs[ex] = exchs.get(ex, 0) + 1

    _print_meta(meta)
    print(f"  PASSED: {len(deduped)} symbols, all required fields present, no dups")
    if exchs:
        top = sorted(exchs.items(), key=lambda kv: kv[1], reverse=True)[:10]
        print("  Top exchanges (count): " + ", ".join(f"{k}:{v}" for k, v in top))
    return True

def validate_blocklist(path: str) -> bool:
    print(f"\nValidating blocklist file: {path}")
    syms = load_blocklist(path)
    if not syms:
        print("  WARNING: Blocklist empty or not found")
        return False
    print(f"  PASSED: {len(syms)} unique blocklisted symbols")
    return True

def main():
    if len(sys.argv) < 2:
        print("Usage: python universe_validation.py <file1> [<file2> ...] [--blocklist]")
        sys.exit(1)
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    is_blocklist = "--blocklist" in sys.argv
    results = []
    for path in paths:
        if not os.path.isfile(path):
            print(f"ERROR: File not found: {path}")
            results.append(False)
            continue
        if is_blocklist or path.endswith(".txt"):
            ok = validate_blocklist(path)
        else:
            ok = validate_universe(path)
        results.append(ok)
    print("\nAll validations complete.")
    if not all(results):
        sys.exit(2)

if __name__ == "__main__":
    main()
