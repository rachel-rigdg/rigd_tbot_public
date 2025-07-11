# tbot_bot/screeners/provider_registry.py
# Central registry for all provider adapters.
# Maps provider names/keys to their respective provider adapter classes.
# Enables dynamic loading and uniform instantiation with injected config/credentials.
# All classes must subclass ProviderBase and never perform env/global reads.

from typing import Type, Dict, Optional

from tbot_bot.screeners.providers.alpaca_provider import AlpacaProvider
from tbot_bot.screeners.providers.finnhub_provider import FinnhubProvider
from tbot_bot.screeners.providers.ibkr_provider import IBKRProvider
from tbot_bot.screeners.providers.polygon_provider import PolygonProvider
from tbot_bot.screeners.providers.tradier_provider import TradierProvider
from tbot_bot.screeners.providers.nasdaq_provider import NasdaqProvider
from tbot_bot.screeners.providers.nasdaq_txt_provider import NasdaqTxtProvider
from tbot_bot.screeners.providers.nyse_provider import NyseProvider
from tbot_bot.screeners.providers.other_txt_provider import OtherTxtProvider
from tbot_bot.screeners.providers.yahoo_provider import YahooProvider

PROVIDER_REGISTRY: Dict[str, Type] = {
    "ALPACA": AlpacaProvider,
    "FINNHUB": FinnhubProvider,
    "IBKR": IBKRProvider,
    "POLYGON": PolygonProvider,
    "TRADIER": TradierProvider,
    "NASDAQ": NasdaqProvider,
    "NASDAQ_TXT": NasdaqTxtProvider,
    "NYSE": NyseProvider,
    "OTHER_TXT": OtherTxtProvider,
    "YAHOO": YahooProvider,
}

def get_provider_class(provider_name: str) -> Optional[Type]:
    """
    Retrieve the provider adapter class by string key (case-insensitive).
    Args:
        provider_name (str): Provider key (e.g., "ALPACA", "NASDAQ").
    Returns:
        Type: Adapter class, or None if not found.
    """
    if not provider_name or not isinstance(provider_name, str):
        return None
    key = provider_name.strip().upper()
    return PROVIDER_REGISTRY.get(key)
