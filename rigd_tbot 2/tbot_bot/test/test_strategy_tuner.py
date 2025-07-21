# tbot_bot/test/test_strategy_selfcheck.py
# Confirms all strategy modules pass .self_check()
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
import unittest
from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path

TEST_FLAG_PATH = get_output_path("control", "test_mode_strategy_selfcheck.flag")
RUN_ALL_FLAG = get_output_path("control", "test_mode.flag")

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_strategy_selfcheck.py] Individual test flag not present. Exiting.")
        sys.exit(0)
else:
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        raise RuntimeError("[test_strategy_selfcheck.py] Individual test flag not present.")

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

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
