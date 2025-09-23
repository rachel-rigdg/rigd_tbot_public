# tbot_bot/screeners/screener_base.py
# Abstract base class for all screener modules within the TradeBot system.
# Enforces usage of the pre-built universe cache adhering strictly to permitted endpoints:
# /stock/symbol, /stock/profile2, /quote only.
#
# Implements core screener workflow:
# - Load validated universe cache
# - Fetch live quotes using subclass-implemented method (must use injected credentials/config only)
# - Filter candidates using subclass-implemented method
#
# Subclasses MUST use the provided credentials/config from secrets_manager.
# No direct environment variable reads or static secret access.
#
# All major events are logged for audit and debugging.

import logging
from typing import List, Dict, Optional

from tbot_bot.screeners.screener_utils import load_universe_cache, UniverseCacheError
from tbot_bot.config.env_bot import load_env_bot_config

LOG = logging.getLogger(__name__)

class ScreenerBase:
    """
    Abstract base class defining the core screener interface and behavior.
    Enforces universe cache loading, indirect credential/config usage, and audit-level logging.

    NOTE: Symbol universe files live at: tbot_bot/output/screeners/
    """

    def __init__(self, bot_identity: Optional[str] = None, creds: Optional[Dict] = None, config: Optional[Dict] = None):
        """
        Initializes the screener:
        - Loads environment configuration for bot identity.
        - Loads and validates the universe cache on instantiation.
        - Accepts injected credentials/config only.
        """
        self.bot_identity = bot_identity
        self.env = config if config is not None else load_env_bot_config()
        self.creds = creds or {}
        self.universe = self._load_universe_cache()

    def _load_universe_cache(self) -> List[Dict]:
        """
        Loads the cached universe from disk, enforcing strict validation.

        Surgical change:
        - Do NOT raise on missing/invalid cache. Instead, log the error and return an empty list
          so concrete screeners (e.g., FinnhubScreener) can perform their own rebuild/fallback.
        - Symbol universe directory is standardized at tbot_bot/output/screeners/.
        """
        try:
            universe = load_universe_cache(self.bot_identity)
            LOG.info(f"[{self.__class__.__name__}] Universe cache loaded with {len(universe)} symbols.")
            return universe
        except UniverseCacheError as e:
            LOG.error(
                f"[{self.__class__.__name__}] Universe cache loading failed: {e}. "
                "Proceeding with empty universe to allow screener-level fallback. "
                "Expected universe location: tbot_bot/output/screeners/"
            )
            # Allow subclass to auto-heal (rebuild/fallback) instead of crashing here.
            return []

    def get_universe(self) -> List[Dict]:
        """
        Returns the currently loaded universe metadata list.
        """
        return self.universe

    def get_symbol_list(self) -> List[str]:
        """
        Extracts and returns a list of all valid symbol strings from the universe cache.
        """
        return [entry["symbol"] for entry in self.universe if "symbol" in entry]

    def run_screen(self) -> List[Dict]:
        """
        Executes the screener process:
        1. Retrieve eligible symbols from the cached universe.
        2. Fetch live quotes/metrics for these symbols (subclass implementation).
        3. Filter live quotes to select trading candidates (subclass implementation).
        Returns the list of filtered symbol dicts ready for trading.
        """
        LOG.info(f"[{self.__class__.__name__}] Starting screener run.")

        universe_symbols = self.get_symbol_list()
        if not universe_symbols:
            LOG.warning(f"[{self.__class__.__name__}] Universe cache empty or no eligible symbols found.")
            return []

        quotes = self.fetch_live_quotes(universe_symbols)
        if not quotes:
            LOG.warning(f"[{self.__class__.__name__}] No live quotes returned for universe symbols.")
            return []

        candidates = self.filter_candidates(quotes)
        LOG.info(f"[{self.__class__.__name__}] Selected {len(candidates)} candidates after filtering.")
        return candidates

    def fetch_live_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Abstract method to fetch live market data for given symbols.
        Must be overridden in subclass.
        Subclass MUST use injected credentials/config loaded from the credential manager,
        not environment variables or static files.
        Returns a list of dictionaries containing live quote data.
        """
        raise NotImplementedError("fetch_live_quotes() must be implemented in subclass.")

    def filter_candidates(self, quotes: List[Dict]) -> List[Dict]:
        """
        Abstract method to filter live quote data into a candidate list for trading.
        Must be overridden in subclass.
        Returns a list of filtered symbol dictionaries.
        """
        raise NotImplementedError("filter_candidates() must be implemented in subclass.")
