# tbot_bot/screeners/universe_diff.py
# Utility for diffing/comparing any two universe or blocklist files (audit/archival/drift detection)
# 100% spec-compliant. Supports JSON and TXT blocklist diff, field-by-field diff, and reporting.
# Usage: python universe_diff.py <file1> <file2> [--blocklist]

import sys
import json
from typing import List, Set, Dict

def load_json_symbols(path: str) -> List[Dict]:
    # Handles both newline-delimited JSON (preferred) and JSON array/object legacy
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        symbols = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                symbols.append(rec)
            except Exception:
                continue
        if symbols:
            return symbols
        # fallback for array/object legacy
        f.seek(0)
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
                syms.add(line.split("|", 1)[0])
    return syms

def diff_blocklists(bl1: Set[str], bl2: Set[str]):
    only_in_1 = sorted(list(bl1 - bl2))
    only_in_2 = sorted(list(bl2 - bl1))
    return only_in_1, only_in_2

def diff_universes(u1: List[Dict], u2: List[Dict]):
    symset1 = set([s.get("symbol", "").upper() for s in u1 if "symbol" in s])
    symset2 = set([s.get("symbol", "").upper() for s in u2 if "symbol" in s])
    only_in_1 = sorted(list(symset1 - symset2))
    only_in_2 = sorted(list(symset2 - symset1))
    changed = []
    u1_map = {s.get("symbol", "").upper(): s for s in u1}
    u2_map = {s.get("symbol", "").upper(): s for s in u2}
    common = symset1 & symset2
    for sym in common:
        s1 = u1_map[sym]
        s2 = u2_map[sym]
        diffs = {}
        for k in set(s1.keys()) | set(s2.keys()):
            v1 = s1.get(k)
            v2 = s2.get(k)
            if v1 != v2:
                diffs[k] = (v1, v2)
        if diffs:
            changed.append({"symbol": sym, "diffs": diffs})
    return only_in_1, only_in_2, changed

def print_diff_result(only_in_1, only_in_2, changed=None, name1="File1", name2="File2"):
    print(f"Symbols only in {name1}: {len(only_in_1)}")
    for s in only_in_1:
        print(f"  {s}")
    print(f"\nSymbols only in {name2}: {len(only_in_2)}")
    for s in only_in_2:
        print(f"  {s}")
    if changed is not None and changed:
        print(f"\nSymbols in both with changed fields: {len(changed)}")
        for ch in changed:
            print(f"  {ch['symbol']}:")
            for k, (v1, v2) in ch["diffs"].items():
                print(f"    {k}: {v1}  ==>  {v2}")

def main():
    if len(sys.argv) < 3:
        print("Usage: python universe_diff.py <file1> <file2> [--blocklist]")
        sys.exit(1)
    file1, file2 = sys.argv[1], sys.argv[2]
    is_blocklist = "--blocklist" in sys.argv
    if is_blocklist:
        bl1 = load_blocklist(file1)
        bl2 = load_blocklist(file2)
        only_in_1, only_in_2 = diff_blocklists(bl1, bl2)
        print_diff_result(only_in_1, only_in_2, name1=file1, name2=file2)
    else:
        u1 = load_json_symbols(file1)
        u2 = load_json_symbols(file2)
        only_in_1, only_in_2, changed = diff_universes(u1, u2)
        print_diff_result(only_in_1, only_in_2, changed, name1=file1, name2=file2)

if __name__ == "__main__":
    main()
