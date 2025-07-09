# tbot_bot/screeners/screener_base.py
# Abstract base class for all broker screener modules.
# Enforces loading and validation of cached universe, provides core interface, and aligns with screener/cache specification.
# STRICT: Only symbols/metadata built from /stock/symbol, /stock/profile2, /quote allowed for universe.

import logging
from typing import List, Dict, Optional

from tbot_bot.screeners.screener_utils import (
    load_universe_cache, UniverseCacheError
)
from tbot_bot.config.env_bot import load_env_bot_config

LOG = logging.getLogger(__name__)

class ScreenerBase:
    """
    Abstract base class for all screener modules.
    Enforces use of universe cache built using ONLY permitted endpoints (/stock/symbol, /stock/profile2, /quote).
    Subclasses must implement fetch_live_quotes() and filter_candidates().
    """
    def __init__(self, bot_identity: Optional[str] = None):
        self.bot_identity = bot_identity
        self.env = load_env_bot_config()
        self.universe = self._load_universe_cache()

    def _load_universe_cache(self) -> List[Dict]:
        """
        Loads and validates the current universe cache.
        Raises UniverseCacheError if unavailable or invalid.
        """
        try:
            universe = load_universe_cache(self.bot_identity)
            LOG.info(f"[{self.__class__.__name__}] Universe cache loaded: {len(universe)} symbols")
            return universe
        except UniverseCacheError as e:
            LOG.error(f"[{self.__class__.__name__}] Universe cache unavailable or invalid: {e}")
            raise

    def get_universe(self) -> List[Dict]:
        """
        Returns the loaded universe (list of symbol metadata dicts).
        """
        return self.universe

    def get_symbol_list(self) -> List[str]:
        """
        Returns a list of eligible symbol strings from universe.
        """
        return [entry["symbol"] for entry in self.universe if "symbol" in entry]

    def run_screen(self) -> List[Dict]:
        """
        Core screener run sequence:
        - Loads universe (built ONLY from /stock/symbol, /stock/profile2, /quote endpoints)
        - Fetches live quotes/metrics for all universe symbols
        - Filters to session candidates via subclass logic
        Returns a list of eligible symbol dicts for trading.
        """
        LOG.info(f"[{self.__class__.__name__}] Screener run started.")

        # 1. Get list of eligible symbols from universe
        universe_symbols = self.get_symbol_list()
        if not universe_symbols:
            LOG.warning(f"[{self.__class__.__name__}] No eligible symbols in universe cache.")
            return []

        # 2. Fetch live quotes for universe (subclass must implement)
        quotes = self.fetch_live_quotes(universe_symbols)
        if not quotes:
            LOG.warning(f"[{self.__class__.__name__}] No live quotes returned for universe symbols.")
            return []

        # 3. Filter candidates for strategy using live data (subclass must implement)
        candidates = self.filter_candidates(quotes)
        LOG.info(f"[{self.__class__.__name__}] {len(candidates)} candidates selected after screener filter.")
        return candidates

    def fetch_live_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Subclass must implement: fetches live quote/metrics for given universe symbols.
        Returns list of symbol dicts with required runtime fields (price, volume, etc).
        """
        raise NotImplementedError("Subclasses must implement fetch_live_quotes()")

    def filter_candidates(self, quotes: List[Dict]) -> List[Dict]:
        """
        Subclass must implement: filters live quotes to strategy-eligible candidates.
        Returns list of symbol dicts for strategy entry.
        """
        raise NotImplementedError("Subclasses must implement filter_candidates()")
