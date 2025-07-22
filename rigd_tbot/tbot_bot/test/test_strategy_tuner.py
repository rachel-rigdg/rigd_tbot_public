# tbot_bot/test/test_strategy_selfcheck.py
# Confirms all strategy modules pass .self_check()
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
import unittest
from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import resolve_control_path

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_strategy_selfcheck.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

def run_and_log():
    result = "PASSED"
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_strategy_selfcheck.py] Individual test flag not present. Exiting.")
        sys.exit(0)
    try:
        unittest.main(module=__name__, exit=False)
    except Exception as e:
        result = "ERRORS"
        safe_print(f"[test_strategy_selfcheck.py] Exception: {e}")
    finally:
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        safe_print(f"[test_strategy_selfcheck.py] FINAL RESULT: {result}")

class TestStrategySelfCheck(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    def test_strategy_selfchecks(self):
        config = get_bot_config()
        failures = []

        if config.get("STRAT_OPEN_ENABLED"):
            try:
                from tbot_bot.strategy.strategy_open import self_check as check_open
                if not check_open():
                    failures.append("strategy_open failed self_check()")
            except Exception as e:
                failures.append(f"strategy_open import/self_check error: {e}")

        if config.get("STRAT_MID_ENABLED"):
            try:
                from tbot_bot.strategy.strategy_mid import self_check as check_mid
                if not check_mid():
                    failures.append("strategy_mid failed self_check()")
            except Exception as e:
                failures.append(f"strategy_mid import/self_check error: {e}")

        if config.get("STRAT_CLOSE_ENABLED"):
            try:
                from tbot_bot.strategy.strategy_close import self_check as check_close
                if not check_close():
                    failures.append("strategy_close failed self_check()")
            except Exception as e:
                failures.append(f"strategy_close import/self_check error: {e}")

        self.assertFalse(failures, "Self-check errors:\n" + "\n".join(failures))

if __name__ == "__main__":
    run_and_log()
