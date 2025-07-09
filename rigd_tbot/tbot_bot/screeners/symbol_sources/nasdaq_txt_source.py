# tbot_bot/screeners/symbol_sources/nasdaq_txt_source.py
# Loader for nasdaqlisted.txt (symbols only, batch ops, normalization).
# 100% compliant with the staged universe/blocklist/adapter spec.

import csv
from typing import List, Dict

def load_nasdaq_txt(path: str) -> List[Dict]:
    """
    Loads symbols from nasdaqlisted.txt file (NASDAQ official list).
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
            symbol = row.get("Symbol")
            name = row.get("Security Name", "")
            if symbol and "Test Issue" not in name:
                syms.append({
                    "symbol": symbol.strip().upper(),
                    "exchange": "NASDAQ",
                    "companyName": name.strip()
                })
    return syms
