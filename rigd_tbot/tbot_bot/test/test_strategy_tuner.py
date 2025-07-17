# tbot_bot/test/test_strategy_selfcheck.py
# Confirms all strategy modules pass .self_check()
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
import unittest
from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_strategy_selfcheck.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        print("[test_strategy_selfcheck.py] Individual test flag not present. Exiting.")
        sys.exit(0)
else:
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        raise RuntimeError("[test_strategy_selfcheck.py] Individual test flag not present.")

class TestStrategySelfCheck(unittest.TestCase):
    def setUp(self):
        if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
            self.skipTest("Individual test flag not present. Exiting.")

    def tearDown(self):
        if TEST_FLAG_PATH.exists():
            TEST_FLAG_PATH.unlink()

    def test_strategy_selfchecks(self):
        """
        Confirms that all enabled strategies pass their .self_check() method.
        This is required before executing any session in production mode.
        Does not launch, run, or supervise any persistent process.
        """
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
