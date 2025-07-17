# tbot_bot/test/test_main_bot.py
# Core lifecycle testing for single-broker unified mode
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
import os
import json
from tbot_bot.runtime import main_bot
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.support.utils_identity import get_bot_identity
from pathlib import Path
import sys

BOT_ID = get_bot_identity()
TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_main_bot.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

LOG_FILES = [
    "open.log",
    "mid.log",
    "close.log",
    "unresolved_orders.log",
    "error_tracebacks.log"
]

TRADE_LOG_JSON = f"{BOT_ID}_BOT_trade_history.json"
TRADE_LOG_CSV = f"{BOT_ID}_BOT_trade_history.csv"

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        print("[test_main_bot.py] Individual test flag not present. Exiting.")
        sys.exit(1)

@pytest.mark.order(1)
def test_main_bot_initialization():
    try:
        main_bot.run_build_check()
    except Exception as e:
        pytest.fail(f"main_bot initialization failed: {e}")

@pytest.mark.order(2)
def test_main_bot_self_check():
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
    for fname in LOG_FILES:
        path = get_output_path("logs", fname)
        assert os.path.exists(path), f"Missing log: {path}"
        assert os.path.getsize(path) > 0, f"Log file is empty: {path}"

@pytest.mark.order(4)
def test_main_bot_trade_log_format():
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

def run_test():
    import pytest as _pytest
    _pytest.main([__file__])
    if TEST_FLAG_PATH.exists():
        TEST_FLAG_PATH.unlink()

if __name__ == "__main__":
    run_test()
