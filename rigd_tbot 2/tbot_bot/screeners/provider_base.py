# tbot_bot/screeners/provider_base.py
# Abstract base class/interface for all provider adapters.
# - All adapters must subclass this and implement fetch_symbols() and fetch_quotes().
# - All adapters must accept injected config/credentials dicts (never read env or globals).
# - No state, no side effects, no internal credential loading.
# - Standardized interface for symbol_source_loader and universe build orchestration.

from typing import List, Dict, Optional

class ProviderBase:
    """
    Abstract base class for modular provider adapters.
    Enforces:
      - Stateless, injected config/credential only
      - Never reads environment or global state
      - All I/O errors must be raised as exceptions, not silenced
    """

    def __init__(self, config: Optional[Dict] = None):
        if config is None or not isinstance(config, dict):
            raise ValueError("ProviderBase requires config dict injection at instantiation.")
        self.config = config

    def fetch_symbols(self) -> List[Dict]:
        """
        Fetch all available symbols from the provider.
        Returns:
            List[Dict]: Each dict must include at minimum:
                {"symbol": str, "exchange": str, "companyName": str}
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
