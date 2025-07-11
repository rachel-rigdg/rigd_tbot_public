# tbot_bot/screeners/providers/nyse_provider.py
# NYSE provider adapter for screener system. 100% ProviderBase-compliant.

from typing import List, Dict, Optional
from tbot_bot.screeners.provider_base import ProviderBase

class NyseProvider(ProviderBase):
    """
    NYSE screener provider: implements fetch_symbols, fetch_quotes, fetch_universe_symbols.
    (IBKR/Polygon-based implementations may be used under the hood.)
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
        Not implemented.
        """
        self.log("fetch_symbols() called but not implemented.")
        raise NotImplementedError("fetch_symbols() not implemented for NyseProvider")

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Return quotes for given NYSE symbols. Not implemented.
        """
        self.log("fetch_quotes() called but not implemented.")
        raise NotImplementedError("fetch_quotes() not implemented for NyseProvider")

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
        Return filtered NYSE universe symbol dicts.
        Not implemented.
        """
        self.log("fetch_universe_symbols() called but not implemented.")
        raise NotImplementedError("fetch_universe_symbols() not implemented for NyseProvider")
