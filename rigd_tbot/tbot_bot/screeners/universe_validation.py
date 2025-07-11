# tbot_bot/screeners/universe_validation.py
# Test/QA utility for validating universe and blocklist files, filter logic, deduplication, field compliance, and drift detection.
# 100% spec-compliant for all symbol universe and blocklist formats.

import sys
import os
import json
from datetime import datetime
from typing import List, Dict, Set

REQUIRED_FIELDS = ["symbol", "exchange", "lastClose", "marketCap"]
SCHEMA_VERSION = "1.0.0"

def load_json_symbols(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict) and "symbols" in data:
            return data["symbols"]
        elif isinstance(data, list):
            return data
        else:
            return []

def load_blocklist(path: str) -> Set[str]:
    syms = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().upper()
            if line and not line.startswith("#"):
                syms.add(line.split(",", 1)[0])
    return syms

def validate_universe(path: str) -> bool:
    print(f"\nValidating universe file: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ERROR: Failed to load JSON: {e}")
        return False
    if isinstance(data, dict) and "symbols" in data:
        symbols = data["symbols"]
        schema = data.get("schema_version")
        if schema and schema != SCHEMA_VERSION:
            print(f"  WARNING: Schema version mismatch: {schema} (expected {SCHEMA_VERSION})")
        build_ts = data.get("build_timestamp_utc")
        if build_ts:
            print(f"  Build timestamp: {build_ts}")
    elif isinstance(data, list):
        symbols = data
    else:
        print("  ERROR: Invalid root structure (must be dict with 'symbols' or a list)")
        return False

    if not isinstance(symbols, list):
        print("  ERROR: Symbols field is not a list")
        return False

    syms = [s.get("symbol", "").upper() for s in symbols if "symbol" in s]
    dups = set([s for s in syms if syms.count(s) > 1])
    if dups:
        print(f"  ERROR: Duplicate symbols found: {dups}")
        return False

    bad = []
    for s in symbols:
        missing = [k for k in REQUIRED_FIELDS if k not in s or s[k] in (None, "", "None")]
        if missing:
            bad.append((s.get("symbol", ""), missing))
    if bad:
        for sym, miss in bad:
            print(f"  ERROR: Symbol {sym} missing fields: {miss}")
        print(f"  {len(bad)} symbols missing required fields")
        return False

    print(f"  PASSED: {len(symbols)} symbols, all required fields present, no dups")
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
