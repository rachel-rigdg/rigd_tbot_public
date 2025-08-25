# tbot_bot/broker/utils/normalizers/__init__.py
# Internal normalizer package.
# Re-exports are ONLY accessible to tbot_bot.broker.utils.ledger_normalizer.
# All other importers are blocked.

import inspect
from types import ModuleType
from typing import Any, Callable, Dict

_ALLOWED_IMPORTERS = {
    "tbot_bot.broker.utils.ledger_normalizer",
}

_EXPORT_LOADERS: Dict[str, Callable[[], Any]] = {
    "normalize_trade_core": lambda: __import__(
        "tbot_bot.broker.utils.normalizers._trades", fromlist=["normalize_trade_core"]
    ).normalize_trade_core,
    "normalize_cash_core": lambda: __import__(
        "tbot_bot.broker.utils.normalizers._cash", fromlist=["normalize_cash_core"]
    ).normalize_cash_core,
    "normalize_position_core": lambda: __import__(
        "tbot_bot.broker.utils.normalizers._positions", fromlist=["normalize_position_core"]
    ).normalize_position_core,
}

__all__ = tuple(_EXPORT_LOADERS.keys())


def _import_allowed() -> bool:
    for frame in inspect.stack():
        mod = frame.frame.f_globals.get("__name__")
        if isinstance(mod, str) and mod in _ALLOWED_IMPORTERS:
            return True
    return False


def __getattr__(name: str) -> Any:
    if name in _EXPORT_LOADERS:
        if not _import_allowed():
            raise ImportError(
                "Normalizers are internal. Import via tbot_bot.broker.utils.ledger_normalizer only."
            )
        return _EXPORT_LOADERS[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + list(__all__))
