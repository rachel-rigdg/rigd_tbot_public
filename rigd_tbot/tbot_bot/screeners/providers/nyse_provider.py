# tbot_bot/screeners/providers/nyse_provider.py
# NYSE provider adapter for screener system. 100% ProviderBase-compliant.

from typing import List, Dict, Optional
from tbot_bot.screeners.provider_base import ProviderBase

class NyseProvider(ProviderBase):
    """
    NYSE screener provider: implements fetch_symbols, fetch_quotes.
    """

    def __init__(self, config: Optional[Dict] = None, creds: Optional[Dict] = None):
        merged = {}
        if config:
            merged.update(config)
        if creds:
            merged.update(creds)
        super().__init__(merged)
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[NyseProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Return NYSE symbols as List[Dict] (symbol, exchange, companyName at minimum).
        Returns empty list and logs warning.
        """
        self.log("fetch_symbols() not implemented for NyseProvider, returning empty list.")
        return []

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Return quotes for given NYSE symbols.
        Returns empty list and logs warning.
        """
        self.log("fetch_quotes() not implemented for NyseProvider, returning empty list.")
        return []
