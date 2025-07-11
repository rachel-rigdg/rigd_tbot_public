# tbot_bot/screeners/providers/yahoo_provider.py
# Yahoo provider adapter: fetches symbols via CSV (exported or compatible), supports injected config.
# 100% ProviderBase-compliant, stateless, config-injected only.

import csv
import os
from typing import List, Dict, Optional

from tbot_bot.screeners.provider_base import ProviderBase

class YahooProvider(ProviderBase):
    """
    Yahoo symbol provider adapter.
    Fetches symbols and metadata from a Yahoo-exported CSV file or compatible source.
    Accepts injected config for input file path (no env reads).
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize with injected config dict (may contain 'csv_path', 'LOG_LEVEL').
        """
        super().__init__(config)
        self.csv_path = self.config.get("csv_path", "yahoo_symbols.csv")
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[YahooProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Loads symbols and metadata from Yahoo-exported CSV file (or compatible).
        Only includes equities with valid symbol and name.
        Returns list of dicts: {symbol, exchange, companyName, sector, industry}
        """
        syms = []
        path = self.csv_path
        if not os.path.isfile(path):
            raise FileNotFoundError(f"[YahooProvider] Symbol CSV not found at path: {path}")
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("Symbol")
                name = row.get("Name") or row.get("Company Name") or ""
                exch = row.get("Exchange", "US")
                sector = row.get("Sector", "")
                industry = row.get("Industry", "")
                if symbol and name and "Test Issue" not in name:
                    syms.append({
                        "symbol": symbol.strip().upper(),
                        "exchange": exch.strip().upper() if exch else "US",
                        "companyName": name.strip(),
                        "sector": sector.strip(),
                        "industry": industry.strip()
                    })
        self.log(f"Loaded {len(syms)} symbols from Yahoo CSV.")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        No live quote support for Yahoo CSV adapter (raise NotImplementedError).
        """
        raise NotImplementedError("[YahooProvider] fetch_quotes() is not implemented for CSV adapter.")

    def fetch_universe_symbols(self, exchanges, min_price, max_price, min_cap, max_cap, blocklist, max_size) -> List[Dict]:
        """
        ProviderBase-compliant stub for universe build. Returns all from CSV if present.
        """
        try:
            symbols = self.fetch_symbols()
        except Exception as e:
            self.log(f"fetch_universe_symbols failed: {e}")
            return []
        return symbols
