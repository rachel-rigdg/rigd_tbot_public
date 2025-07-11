# tbot_bot/screeners/providers/nasdaq_txt_provider.py
# Nasdaqlisted.txt provider adapter: downloads/parses symbols from NASDAQ official txt, no credentials required.
# 100% ProviderBase-compliant, stateless, config-injected only.

import csv
import os
import requests
from typing import List, Dict, Optional

from tbot_bot.screeners.provider_base import ProviderBase

NASDAQ_TXT_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"

class NasdaqTxtProvider(ProviderBase):
    """
    Provider adapter for nasdaqlisted.txt file.
    Downloads and parses NASDAQ official symbol list as needed.
    """

    def __init__(self, config: Optional[Dict] = None):
        print("NasdaqTxtProvider instantiated!")  # DEBUG
        super().__init__(config)
        self.local_path = self.config.get("local_path", "nasdaqlisted.txt")
        self.force_download = bool(self.config.get("force_download", False))
        self.fetch_if_missing = bool(self.config.get("fetch_if_missing", True))
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[NasdaqTxtProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Downloads and parses nasdaqlisted.txt if missing or forced.
        Returns list of dicts: {symbol, exchange, companyName}
        """
        self._fetch_txt_if_needed()
        return self._load_from_txt()

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Not supported for TXT provider (no quotes in file).
        Returns empty list.
        """
        self.log("fetch_quotes() called on TXT provider; not supported.")
        return []

    def fetch_universe_symbols(self, exchanges, min_price, max_price, min_cap, max_cap, blocklist, max_size) -> List[Dict]:
        print("NasdaqTxtProvider.fetch_universe_symbols CALLED!")  # DEBUG
        """
        ProviderBase-compliant stub for universe build. Returns all from TXT.
        """
        try:
            symbols = self.fetch_symbols()
        except Exception as e:
            self.log(f"fetch_universe_symbols failed: {e}")
            return []
        return symbols

    def _fetch_txt_if_needed(self):
        """
        Downloads nasdaqlisted.txt if file missing or force_download=True.
        """
        if not os.path.isfile(self.local_path) or self.force_download:
            resp = requests.get(NASDAQ_TXT_URL, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"[NasdaqTxtProvider] Failed to fetch nasdaqlisted.txt: status {resp.status_code}")
            with open(self.local_path, "w", encoding="utf-8") as f:
                f.write(resp.text)
            self.log(f"Downloaded nasdaqlisted.txt to {self.local_path}.")

    def _load_from_txt(self) -> List[Dict]:
        """
        Loads and parses nasdaqlisted.txt into symbol dicts.
        Skips test issues, placeholders, and blanks.
        """
        syms = []
        with open(self.local_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(
                (line for line in f if line.strip() and not line.startswith("File")),
                delimiter="|"
            )
            for row in reader:
                symbol = row.get("Symbol", "").strip().upper()
                name = row.get("Security Name", "").strip()
                if not symbol or "Test Issue" in name or symbol.startswith("ZVZZT"):
                    continue
                syms.append({
                    "symbol": symbol,
                    "exchange": "NASDAQ",
                    "companyName": name
                })
        self.log(f"Loaded {len(syms)} NASDAQ symbols from TXT.")
        return syms
