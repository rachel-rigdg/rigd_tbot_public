# tbot_bot/screeners/provider_registry.py
# Central registry for all provider adapters.
# Maps provider names/keys to their respective provider adapter classes and import paths.
# Enables dynamic loading and uniform instantiation with injected config/credentials.
# All classes must subclass ProviderBase and never perform env/global reads.

from typing import Type, Dict, Optional

from tbot_bot.screeners.providers.finnhub_provider import FinnhubProvider
from tbot_bot.screeners.providers.ibkr_provider import IBKRProvider
from tbot_bot.screeners.providers.nasdaq_provider import NasdaqProvider
from tbot_bot.screeners.providers.nasdaq_txt_provider import NasdaqTxtProvider
from tbot_bot.screeners.providers.nyse_provider import NyseProvider
from tbot_bot.screeners.providers.yahoo_provider import YahooProvider

PROVIDER_REGISTRY: Dict[str, Type] = {
    "FINNHUB": FinnhubProvider,
    "IBKR": IBKRProvider,
    "NASDAQ_TXT": NasdaqTxtProvider,
    "NASDAQ": NasdaqProvider,
    "NYSE": NyseProvider,
    "YAHOO": YahooProvider,
}

PROVIDER_MODULE_PATHS: Dict[str, str] = {
    "FINNHUB": "tbot_bot.screeners.providers.finnhub_provider",
    "IBKR": "tbot_bot.screeners.providers.ibkr_provider",
    "NASDAQ": "tbot_bot.screeners.providers.nasdaq_provider",
    "NASDAQ_TXT": "tbot_bot.screeners.providers.nasdaq_txt_provider",
    "NYSE": "tbot_bot.screeners.providers.nyse_provider",
    "YAHOO": "tbot_bot.screeners.providers.yahoo_provider",
}

PROVIDER_CLASS_NAMES: Dict[str, str] = {
    "FINNHUB": "FinnhubProvider",
    "IBKR": "IBKRProvider",
    "NASDAQ": "NasdaqProvider",
    "NASDAQ_TXT": "NasdaqTxtProvider",
    "NYSE": "NyseProvider",
    "YAHOO": "YahooProvider",
}

def get_provider_class(provider_name: str) -> Optional[Type]:
    if not provider_name or not isinstance(provider_name, str):
        return None
    key = provider_name.strip().upper()
    return PROVIDER_REGISTRY.get(key)

def get_provider_module_path(provider_name: str) -> Optional[str]:
    if not provider_name or not isinstance(provider_name, str):
        return None
    key = provider_name.strip().upper()
    return PROVIDER_MODULE_PATHS.get(key)

def get_provider_class_name(provider_name: str) -> Optional[str]:
    if not provider_name or not isinstance(provider_name, str):
        return None
    key = provider_name.strip().upper()
    return PROVIDER_CLASS_NAMES.get(key)
