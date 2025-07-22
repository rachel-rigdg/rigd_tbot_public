# tbot_bot/test/test_strategy_selfcheck.py
# Confirms all strategy modules pass .self_check()
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import resolve_control_path
from pathlib import Path
import sys
import subprocess

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_strategy_selfcheck.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
TIMEOUT_SECONDS = 30

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

def run_self_check_subprocess(module_path: str) -> bool:
    """
    Runs the self_check function of the specified module in a subprocess,
    enforcing a TIMEOUT_SECONDS limit.
    Returns True if self_check() returns True, else False.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module_path}; exit(0) if {module_path}.self_check() else exit(1)"],
            timeout=TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        safe_print(f"[test_strategy_selfcheck] Timeout: {module_path} self_check exceeded {TIMEOUT_SECONDS} seconds.")
        return False
    except Exception as e:
        safe_print(f"[test_strategy_selfcheck] Error running {module_path}.self_check(): {e}")
        return False

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_strategy_selfcheck.py] Individual test flag not present. Exiting.")
        sys.exit(0)

class TestStrategySelfCheck(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    def test_strategy_selfchecks(self):
        safe_print("[test_strategy_selfcheck] Running strategy selfchecks...")
        config = get_bot_config()
        failures = []

        if config.get("STRAT_OPEN_ENABLED"):
            if not run_self_check_subprocess("tbot_bot.strategy.strategy_open"):
                failures.append("strategy_open failed self_check() or timed out")

        if config.get("STRAT_MID_ENABLED"):
            if not run_self_check_subprocess("tbot_bot.strategy.strategy_mid"):
                failures.append("strategy_mid failed self_check() or timed out")

        if config.get("STRAT_CLOSE_ENABLED"):
            if not run_self_check_subprocess("tbot_bot.strategy.strategy_close"):
                failures.append("strategy_close failed self_check() or timed out")

        self.assertFalse(failures, "Self-check errors:\n" + "\n".join(failures))
        safe_print("[test_strategy_selfcheck] PASSED.")

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
