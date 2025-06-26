# tbot_bot/test/test_env_bot.py
# Validates .env_bot parsing, defaults, and edge cases
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# All process orchestration is via tbot_supervisor.py only.

import pytest
from tbot_bot.config.env_bot import get_bot_config

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

def test_all_required_keys_present():
    config = get_bot_config()
    missing_keys = [key for key in REQUIRED_KEYS if key not in config]
    assert not missing_keys, f"Missing keys in env_bot config: {missing_keys}"

def test_value_types():
    config = get_bot_config()
    assert isinstance(config["ENABLE_LOGGING"], bool)
    assert isinstance(config["TOTAL_ALLOCATION"], float)
    assert isinstance(config["MAX_RISK_PER_TRADE"], float)
    assert isinstance(config["MAX_OPEN_POSITIONS"], int)
    assert isinstance(config["SLEEP_TIME"], str)
    assert isinstance(config["DAILY_LOSS_LIMIT"], float)
    assert isinstance(config["FRACTIONAL"], bool)
    assert isinstance(config["DISABLE_ALL_TRADES"], bool)

def test_strategy_toggles():
    config = get_bot_config()
    assert isinstance(config["STRAT_OPEN_ENABLED"], bool)
    assert isinstance(config["STRAT_MID_ENABLED"], bool)
    assert isinstance(config["STRAT_CLOSE_ENABLED"], bool)

def test_logging_format():
    config = get_bot_config()
    assert config["LOG_FORMAT"] in ["csv", "json"]
