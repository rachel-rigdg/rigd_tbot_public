# tbot_bot/test/test_main_bot.py
# Core lifecycle testing for single-broker unified mode
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
import os
import json
import signal
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path, resolve_control_path
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys

MAX_TEST_TIME = 90  # seconds per test

BOT_ID = get_bot_identity()
CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_main_bot.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
LOGFILE = get_output_path("logs", "test_mode.log")

LOG_FILES = [
    "open.log",
    "mid.log",
    "close.log",
    "unresolved_orders.log",
    "error_tracebacks.log"
]

TRADE_LOG_JSON = f"{BOT_ID}_BOT_trade_history.json"
TRADE_LOG_CSV = f"{BOT_ID}_BOT_trade_history.csv"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_main_bot", msg, logfile=LOGFILE)
    except Exception:
        pass

def timeout_handler(signum, frame):
    safe_print("[test_main_bot] TIMEOUT")
    pytest.fail("test_main_bot timed out")
    sys.exit(1)

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_main_bot.py] Individual test flag not present. Exiting.")
        sys.exit(1)

@pytest.mark.order(1)
def test_main_bot_initialization():
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_TEST_TIME)
    try:
        from tbot_bot.runtime import main as main_bot
        if hasattr(main_bot, "run_build_check"):
            main_bot.run_build_check()
            safe_print("[test_main_bot] Initialization PASSED.")
        else:
            safe_print("[test_main_bot] Initialization SKIPPED: run_build_check not implemented.")
    finally:
        signal.alarm(0)

@pytest.mark.order(2)
def test_main_bot_self_check():
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_TEST_TIME)
    try:
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
        if errors:
            safe_print("[test_main_bot] Self_check errors: " + ", ".join(errors))
        assert not errors, "Strategy self_check failures: " + ", ".join(errors)
    finally:
        signal.alarm(0)

@pytest.mark.order(3)
def test_main_bot_logs_created():
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_TEST_TIME)
    try:
        for fname in LOG_FILES:
            path = get_output_path("logs", fname)
            if not os.path.exists(path):
                safe_print(f"[test_main_bot] Missing log: {path}")
            assert os.path.exists(path), f"Missing log: {path}"
            if os.path.getsize(path) == 0:
                safe_print(f"[test_main_bot] Log file is empty: {path}")
            assert os.path.getsize(path) > 0, f"Log file is empty: {path}"
    finally:
        signal.alarm(0)

@pytest.mark.order(4)
def test_main_bot_trade_log_format():
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_TEST_TIME)
    try:
        path = get_output_path("trades", TRADE_LOG_JSON)
        if not os.path.exists(path):
            safe_print(f"[test_main_bot] Missing trade history JSON log: {path}")
        assert os.path.exists(path), "Missing trade history JSON log"
        with open(path, "r") as f:
            lines = [json.loads(line.strip()) for line in f if line.strip()]
        assert isinstance(lines, list)
        for entry in lines:
            for field in ["strategy", "ticker", "side"]:
                if field not in entry:
                    safe_print(f"[test_main_bot] Trade log missing field: {field}")
                assert field in entry
            if not ("entry_price" in entry or "price" in entry):
                safe_print(f"[test_main_bot] Trade log missing entry_price/price: {entry}")
            assert "entry_price" in entry or "price" in entry
            if "exit_price" not in entry:
                safe_print(f"[test_main_bot] Trade log missing exit_price: {entry}")
            assert "exit_price" in entry
            if "PnL" not in entry:
                safe_print(f"[test_main_bot] Trade log missing PnL: {entry}")
            assert "PnL" in entry
    finally:
        signal.alarm(0)

def run_test():
    import pytest as _pytest
    ret = _pytest.main([__file__])
    result = "PASSED" if ret == 0 else "ERRORS"
    safe_print(f"[test_main_bot.py] FINAL RESULT: {result}")
    if Path(TEST_FLAG_PATH).exists():
        Path(TEST_FLAG_PATH).unlink()

if __name__ == "__main__":
    run_test()
