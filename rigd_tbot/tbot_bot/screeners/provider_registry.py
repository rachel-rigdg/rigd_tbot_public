# tbot_bot/screeners/provider_registry.py
# Central registry for all provider adapters.
# Maps provider names/keys to their respective provider adapter classes and import paths.
# Enables dynamic loading and uniform instantiation with injected config/credentials.
# All classes must subclass ProviderBase and never perform env/global reads.

from typing import Type, Dict, Optional, List, Tuple

from tbot_bot.screeners.providers.finnhub_provider import FinnhubProvider
from tbot_bot.screeners.providers.ibkr_provider import IBKRProvider
from tbot_bot.screeners.providers.nasdaq_provider import NasdaqProvider
from tbot_bot.screeners.providers.nyse_provider import NyseProvider
from tbot_bot.screeners.providers.yahoo_provider import YahooProvider

# Optional: secrets loader used ONLY for enabled-provider discovery (no implicit fallbacks here)
from tbot_bot.support.secrets_manager import load_screener_credentials

PROVIDER_REGISTRY: Dict[str, Type] = {
    "FINNHUB": FinnhubProvider,
    "IBKR": IBKRProvider,
    "NASDAQ": NasdaqProvider,
    "NYSE": NyseProvider,
    "YAHOO": YahooProvider,
}

PROVIDER_MODULE_PATHS: Dict[str, str] = {
    "FINNHUB": "tbot_bot.screeners.providers.finnhub_provider",
    "IBKR": "tbot_bot.screeners.providers.ibkr_provider",
    "NASDAQ": "tbot_bot.screeners.providers.nasdaq_provider",
    "NYSE": "tbot_bot.screeners.providers.nyse_provider",
    "YAHOO": "tbot_bot.screeners.providers.yahoo_provider",
}

PROVIDER_CLASS_NAMES: Dict[str, str] = {
    "FINNHUB": "FinnhubProvider",
    "IBKR": "IBKRProvider",
    "NASDAQ": "NasdaqProvider",
    "NYSE": "NyseProvider",
    "YAHOO": "YahooProvider",
}

# -------------------------------
# Normalization / helper utilities
# -------------------------------
def _norm(name: Optional[str]) -> Optional[str]:
    return name.strip().upper() if isinstance(name, str) else None

def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _discover_indexed_providers(secrets: Dict[str, str]) -> List[Tuple[str, str]]:
    """
    Return list of (PROVIDER_NAME_UPPER, INDEX_STR).
    """
    out: List[Tuple[str, str]] = []
    for k, v in secrets.items():
        if not k.startswith("PROVIDER_"):
            continue
        idx = k.split("_")[-1]
        name = _norm(v)
        if name:
            out.append((name, idx))
    return out

# -------------------------------------------
# Single source of truth for "enabled" status
# -------------------------------------------
def get_enabled_providers(flag_key: str = "UNIVERSE_ENABLED", secrets: Optional[Dict[str, str]] = None) -> List[str]:
    """
    Returns a list of provider names (UPPERCASE) that are explicitly enabled for the given flag_key.
    No implicit fallbacks: if none enabled, returns [].
    """
    secrets = secrets if isinstance(secrets, dict) else (load_screener_credentials() or {})
    enabled: List[str] = []
    for name, idx in _discover_indexed_providers(secrets):
        enabled_flag = secrets.get(f"{flag_key}_{idx}", "")
        if _truthy(enabled_flag):
            enabled.append(name)
    return enabled

def is_provider_enabled(provider_name: str, flag_key: str = "UNIVERSE_ENABLED", secrets: Optional[Dict[str, str]] = None) -> bool:
    """
    True if and only if the specific provider_name is explicitly enabled for the given purpose.
    """
    name = _norm(provider_name)
    if not name:
        return False
    return name in get_enabled_providers(flag_key=flag_key, secrets=secrets)

def get_provider_class_strict(provider_name: str, flag_key: str = "UNIVERSE_ENABLED", secrets: Optional[Dict[str, str]] = None) -> Optional[Type]:
    """
    Returns the provider class ONLY if that provider is explicitly enabled for the given purpose.
    No implicit fallbacks. Returns None if disabled/unknown.
    """
    name = _norm(provider_name)
    if not name:
        return None
    if not is_provider_enabled(name, flag_key=flag_key, secrets=secrets):
        return None
    return PROVIDER_REGISTRY.get(name)

# -----------------------
# Legacy lookup functions
# -----------------------
def get_provider_class(provider_name: str) -> Optional[Type]:
    """
    Legacy: simple registry lookup by name (does NOT check enabled state).
    Prefer get_provider_class_strict() when enforcing enabled-policy.
    """
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
