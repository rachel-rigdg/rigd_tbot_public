# tbot_bot/test/test_main_bot.py
# Core lifecycle testing for single-broker unified mode

import pytest
import os
import json
from tbot_bot.runtime import main_bot
from tbot_bot.config.env_bot import get_bot_config, env_config
from tbot_bot.support.path_resolver import get_output_path

BOT_ID = env_config["BOT_IDENTITY_STRING"]

LOG_FILES = [
    "open.log",
    "mid.log",
    "close.log",
    "unresolved_orders.log",
    "error_tracebacks.log"
]

TRADE_LOG_JSON = f"{BOT_ID}_BOT_trade_history.json"
TRADE_LOG_CSV = f"{BOT_ID}_BOT_trade_history.csv"

@pytest.mark.order(1)
def test_main_bot_initialization():
    """
    Ensure the main_bot can initialize without raising errors.
    """
    try:
        main_bot.run_build_check()
    except Exception as e:
        pytest.fail(f"main_bot initialization failed: {e}")

@pytest.mark.order(2)
def test_main_bot_self_check():
    """
    Verifies that self_check passes for all enabled strategies in config.
    """
    config = get_bot_config()
    errors = []

    if config.get("STRAT_OPEN_ENABLED"):
        from tbot_bot.strategy.strategy_open import self_check as open_check
        if not open_check():
            errors.append("strategy_open failed self_check")

    if config.get("STRAT_MID_ENABLED"):
        from tbot_bot.strategy.strategy_mid import self_check as mid_check
        if not mid_check():
            errors.append("strategy_mid failed self_check")

    if config.get("STRAT_CLOSE_ENABLED"):
        from tbot_bot.strategy.strategy_close import self_check as close_check
        if not close_check():
            errors.append("strategy_close failed self_check")

    assert not errors, "Strategy self_check failures: " + ", ".join(errors)

@pytest.mark.order(3)
def test_main_bot_logs_created():
    """
    Confirms that expected output logs exist and are non-empty.
    """
    for fname in LOG_FILES:
        path = get_output_path("logs", fname)
        assert os.path.exists(path), f"Missing log: {path}"
        assert os.path.getsize(path) > 0, f"Log file is empty: {path}"

@pytest.mark.order(4)
def test_main_bot_trade_log_format():
    """
    Validates that BOT_trade_history.json has properly structured entries.
    """
    path = get_output_path("trades", TRADE_LOG_JSON)
    assert os.path.exists(path), "Missing trade history JSON log"

    with open(path, "r") as f:
        lines = [json.loads(line.strip()) for line in f if line.strip()]

    assert isinstance(lines, list)
    for entry in lines:
        assert "strategy" in entry
        assert "ticker" in entry
        assert "side" in entry
        assert "entry_price" in entry or "price" in entry
        assert "exit_price" in entry
        assert "PnL" in entry
