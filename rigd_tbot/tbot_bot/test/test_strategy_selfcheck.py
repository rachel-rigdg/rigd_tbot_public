# tbot_bot/test/test_strategy_selfcheck.py
# Confirms all strategy modules pass .self_check()
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys
import subprocess
import signal
from datetime import datetime, timezone
print(f"[LAUNCH] test_strategy_selfcheck launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_strategy_selfcheck.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
LOGFILE = get_output_path("logs", "test_mode.log")
MAX_TEST_TIME = 90  # seconds per test

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_strategy_selfcheck", msg, logfile=LOGFILE)
    except Exception:
        pass

def timeout_handler(signum, frame):
    safe_print("[test_strategy_selfcheck] TIMEOUT")
    raise TimeoutError("test_strategy_selfcheck timed out")

def run_self_check_subprocess(module_path: str) -> bool:
    """
    Runs the self_check function of the specified module in a subprocess,
    enforcing a MAX_TEST_TIME limit.
    Returns True if self_check() returns True, else False.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module_path}; exit(0) if {module_path}.self_check() else exit(1)"],
            timeout=MAX_TEST_TIME,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            safe_print(f"[test_strategy_selfcheck] {module_path}.self_check() FAILED.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        safe_print(f"[test_strategy_selfcheck] Timeout: {module_path} self_check exceeded {MAX_TEST_TIME} seconds.")
        return False
    except Exception as e:
        safe_print(f"[test_strategy_selfcheck] Error running {module_path}.self_check(): {e}")
        return False

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_strategy_selfcheck.py] Individual test flag not present. Exiting.")
        sys.exit(0)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_TEST_TIME)

class TestStrategySelfCheck(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(MAX_TEST_TIME)

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        signal.alarm(0)

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

        if failures:
            safe_print("[test_strategy_selfcheck] ERRORS:\n" + "\n".join(failures))
        else:
            safe_print("[test_strategy_selfcheck] PASSED.")

        self.assertFalse(failures, "Self-check errors:\n" + "\n".join(failures))
        safe_print(f"[test_strategy_selfcheck] FINAL RESULT: {'ERRORS' if failures else 'PASSED'}.")

def run_test():
    unittest.main(module=__name__, exit=False)
    signal.alarm(0)

if __name__ == "__main__":
    run_test()
