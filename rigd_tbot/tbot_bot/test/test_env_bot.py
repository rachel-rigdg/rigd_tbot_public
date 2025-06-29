# tbot_bot/test/test_env_bot.py
# Validates .env_bot parsing, defaults, and edge cases
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
from tbot_bot.config.env_bot import get_bot_config
from pathlib import Path
import sys

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_env_bot.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

REQUIRED_KEYS = [
    "VERSION_TAG",
    "BUILD_MODE",
    "DISABLE_ALL_TRADES",
    "DEBUG_LOG_LEVEL",
    "ENABLE_LOGGING",
    "LOG_FORMAT",
    "TRADE_CONFIRMATION_REQUIRED",
    "API_RETRY_LIMIT",
    "FRACTIONAL",
    "TOTAL_ALLOCATION",
    "MAX_TRADES",
    "WEIGHTS",
    "DAILY_LOSS_LIMIT",
    "MAX_RISK_PER_TRADE",
    "MAX_OPEN_POSITIONS",
    "MIN_PRICE",
    "MAX_PRICE",
    "MIN_VOLUME_THRESHOLD",
    "STRATEGY_SEQUENCE",
    "STRATEGY_OVERRIDE",
    "TRADING_DAYS",
    "SLEEP_TIME",

    # Open strategy
    "STRAT_OPEN_ENABLED",
    "START_TIME_OPEN",
    "OPEN_ANALYSIS_TIME",
    "OPEN_MONITORING_TIME",
    "STRAT_OPEN_BUFFER",
    "SHORT_TYPE_OPEN",

    # Mid strategy
    "STRAT_MID_ENABLED",
    "START_TIME_MID",
    "MID_ANALYSIS_TIME",
    "MID_MONITORING_TIME",
    "STRAT_MID_VWAP_THRESHOLD",
    "SHORT_TYPE_MID",

    # Close strategy
    "STRAT_CLOSE_ENABLED",
    "START_TIME_CLOSE",
    "CLOSE_ANALYSIS_TIME",
    "CLOSE_MONITORING_TIME",
    "STRAT_CLOSE_VIX_THRESHOLD",
    "SHORT_TYPE_CLOSE",

    # Notifications
    "NOTIFY_ON_FILL",
    "NOTIFY_ON_EXIT"
]

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        print("[test_env_bot.py] Individual test flag not present. Exiting.")
        sys.exit(1)

def test_all_required_keys_present():
    config = get_bot_config()
    missing_keys = [key for key in REQUIRED_KEYS if key not in config]
    assert not missing_keys, f"Missing keys in env_bot config: {missing_keys}"

def test_value_types():
    config = get_bot_config()
    assert isinstance(config.get("ENABLE_LOGGING"), bool)
    assert isinstance(config.get("TOTAL_ALLOCATION"), float)
    assert isinstance(config.get("MAX_RISK_PER_TRADE"), float)
    assert isinstance(config.get("MAX_OPEN_POSITIONS"), int)
    assert isinstance(config.get("SLEEP_TIME"), str)
    assert isinstance(config.get("DAILY_LOSS_LIMIT"), float)
    assert isinstance(config.get("FRACTIONAL"), bool)
    assert isinstance(config.get("DISABLE_ALL_TRADES"), bool)

def test_strategy_toggles():
    config = get_bot_config()
    assert isinstance(config.get("STRAT_OPEN_ENABLED"), bool)
    assert isinstance(config.get("STRAT_MID_ENABLED"), bool)
    assert isinstance(config.get("STRAT_CLOSE_ENABLED"), bool)

def test_logging_format():
    config = get_bot_config()
    assert config.get("LOG_FORMAT") in ["csv", "json"]

def run_test():
    import unittest
    try:
        unittest.main(module=__name__, exit=False)
    finally:
        if TEST_FLAG_PATH.exists():
            TEST_FLAG_PATH.unlink()

if __name__ == "__main__":
    run_test()
