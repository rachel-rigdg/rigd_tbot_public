# tbot_bot/screeners/providers/other_txt_provider.py
# Generic TXT provider adapter: loads symbols from TXT/CSV files (AMEX, OTC, custom lists, etc).
# No credentials required for file-based symbol fetch. Quotes via IBKR if needed.
# Fully self-contained and stateless per specification.

import csv
import os
from typing import List, Dict, Optional
from tbot_bot.screeners.provider_base import ProviderBase

class OtherTxtProvider(ProviderBase):
    """
    ProviderBase-compliant adapter for generic TXT symbol files.
    """

    def __init__(self, config: Optional[Dict] = None, creds: Optional[Dict] = None):
        merged = {}
        if config:
            merged.update(config)
        if creds:
            merged.update(creds)
        super().__init__(merged)
        self.local_path = self.config.get("local_path", "otherlisted.txt")
        self.exchange = self.config.get("exchange", "OTHER")
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[OtherTxtProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Loads symbols from a TXT/CSV file with columns: Symbol, Security Name.
        Only includes valid symbols (non-empty, non-placeholder).
        Returns list of dicts: {symbol, exchange, companyName}
        """
        path = self.local_path
        exchange = self.exchange
        if not os.path.isfile(path):
            raise RuntimeError(f"[other_txt_provider] File not found: {path}")

        syms = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader((line for line in f if line.strip()), delimiter="|")
            for row in reader:
                symbol = row.get("Symbol", "").strip().upper()
                name = row.get("Security Name", "").strip()
                if not symbol or "Test Issue" in name or symbol.startswith("ZVZZT"):
                    continue
                syms.append({
                    "symbol": symbol,
                    "exchange": exchange.upper(),
                    "companyName": name
                })
        self.log(f"Loaded {len(syms)} symbols from {path} ({exchange}).")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Not implemented: must be handled by enrichment provider.
        """
        self.log("fetch_quotes() called but not implemented.")
        raise NotImplementedError("fetch_quotes() not implemented for OtherTxtProvider")

    def fetch_universe_symbols(
        self,
        exchanges: List[str],
        min_price: float,
        max_price: float,
        min_cap: float,
        max_cap: float,
        blocklist: Optional[List[str]] = None,
        max_size: Optional[int] = None
    ) -> List[Dict]:
        """
        Not implemented: must be handled by enrichment provider or specific loader.
        """
        self.log("fetch_universe_symbols() called but not implemented.")
        raise NotImplementedError("fetch_universe_symbols() not implemented for OtherTxtProvider")
