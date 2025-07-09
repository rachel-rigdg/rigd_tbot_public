# tbot_bot/screeners/symbol_sources/other_txt_source.py
# Loader for otherlisted.txt (batch ops, normalization).
# 100% compliant with v046 staged universe/blocklist/adapter spec.

import csv
from typing import List, Dict

def load_otherlisted_txt(path: str) -> List[Dict]:
    """
    Loads symbols from otherlisted.txt file (typically NYSE/ARCA official list).
    Only includes valid, non-test issues.
    Returns list of dicts: {symbol, exchange, companyName}
    """
    syms = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(
            (line for line in f if not line.startswith("File") and not line.startswith("\n")),
            delimiter="|"
        )
        for row in reader:
            symbol = row.get("ACT Symbol") or row.get("Symbol")
            exch = row.get("Exchange", "NYSE")
            name = row.get("Security Name", "")
            if symbol and "Test Issue" not in name:
                syms.append({
                    "symbol": symbol.strip().upper(),
                    "exchange": exch.strip().upper() if exch else "NYSE",
                    "companyName": name.strip()
                })
    return syms
