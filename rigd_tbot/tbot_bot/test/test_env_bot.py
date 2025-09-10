# tbot_bot/test/test_env_bot.py
# Validates .env_bot parsing, defaults, and edge cases
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
import time
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys
from datetime import datetime, timezone
print(f"[LAUNCH] test_env_bot launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
LOGFILE = get_output_path("logs", "test_mode.log")
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_env_bot.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

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
    "STRATEGY_SLEEP_TIME",  # renamed from SLEEP_TIME
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

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_env_bot", msg, logfile=LOGFILE)
    except Exception:
        pass

test_start = time.time()

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_env_bot.py] Individual test flag not present. Exiting.")
        sys.exit(1)

def test_all_required_keys_present():
    config = get_bot_config()
    missing_keys = [key for key in REQUIRED_KEYS if key not in config]
    assert not missing_keys, f"Missing keys in env_bot config: {missing_keys}"

def test_value_types():
    config = get_bot_config()
    def as_float(val):
        try:
            return float(val)
        except Exception:
            return val
    def as_int(val):
        try:
            return int(val)
        except Exception:
            return val
    assert isinstance(config.get("ENABLE_LOGGING"), bool)
    assert isinstance(as_float(config.get("TOTAL_ALLOCATION")), float)
    assert isinstance(as_float(config.get("MAX_RISK_PER_TRADE")), float)
    assert isinstance(as_int(config.get("MAX_OPEN_POSITIONS")), int)
    assert isinstance(config.get("STRATEGY_SLEEP_TIME"), str)  # renamed from SLEEP_TIME
    assert isinstance(as_float(config.get("DAILY_LOSS_LIMIT")), float)
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
    import pytest as _pytest
    ret = _pytest.main([__file__])
    status = "PASSED" if ret == 0 else "ERRORS"
    if (time.time() - test_start) > MAX_TEST_TIME:
        status = "TIMEOUT"
        safe_print(f"[test_env_bot.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
    if Path(TEST_FLAG_PATH).exists():
        Path(TEST_FLAG_PATH).unlink()
    safe_print(f"[test_env_bot.py] FINAL RESULT: {status}")

if __name__ == "__main__":
    run_test()
