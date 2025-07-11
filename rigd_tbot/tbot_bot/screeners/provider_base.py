# tbot_bot/screeners/provider_base.py
# Abstract base class/interface for all provider adapters.
# - All adapters must subclass this and implement both fetch_symbols() and fetch_quotes().
# - All adapters must accept injected config/credentials dicts (never read env or globals).
# - No state, no side effects, no internal credential loading.
# - Standardized interface for symbol_source_loader and universe build orchestration.

import logging
from typing import List, Dict, Optional

LOG = logging.getLogger(__name__)

class ProviderBase:
    """
    Abstract base class for modular provider adapters.
    Enforces:
      - Stateless, injected config/credential only
      - Never reads environment or global state
      - All I/O errors must be raised as exceptions, not silenced
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the provider with injected config dictionary.
        No provider may access environment variables, globals, or internal credential loaders.
        """
        print(f"ProviderBase __init__ called with config={config} ({type(config)})")  # DEBUG TRACE
        if config is None or not isinstance(config, dict):
            raise ValueError("ProviderBase requires config dict injection at instantiation.")
        self.config = config

    def fetch_symbols(self) -> List[Dict]:
        """
        Fetch all available symbols from the provider.
        Returns:
            List[Dict]: Each dict must include at minimum:
                {"symbol": str, "exchange": str, "name": str or "companyName"}
        Must be implemented in subclass.
        """
        raise NotImplementedError("Provider adapter must implement fetch_symbols().")

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Fetch latest quotes/metrics for a list of symbols.
        Returns:
            List[Dict]: Each dict must include required runtime fields for screening:
                e.g. {"symbol": str, "c": float, "o": float, "vwap": float, ...}
        Must be implemented in subclass.
        """
        raise NotImplementedError("Provider adapter must implement fetch_quotes().")

    def fetch_universe_symbols(
        self,
        exchanges: List[str],
        min_price: float,
        max_price: float,
        min_cap: float,
        max_cap: float,
        blocklist: List[str] = None,
        max_size: int = None
    ) -> List[Dict]:
        """
        Fetch and filter universe symbols for build using injected config and arguments.
        Returns a list of normalized, deduped symbol dicts ready for cache.
        This is the main entrypoint for symbol_universe_refresh orchestration.
        Must be implemented in subclass.
        """
        raise NotImplementedError("Provider adapter must implement fetch_universe_symbols().")
