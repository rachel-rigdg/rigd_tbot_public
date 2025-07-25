# tbot_bot/test/test_screener_integration.py
# Integration tests for screener modules using universe cache
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# STRICT: Test will only exercise /stock/symbol, /stock/profile2, /quote endpoints for Finnhub screener.

import unittest
import signal
from tbot_bot.screeners.screeners.alpaca_screener import AlpacaScreener
from tbot_bot.screeners.screeners.finnhub_screener import FinnhubScreener
from tbot_bot.screeners.screeners.ibkr_screener import IBKRScreener
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from pathlib import Path
import sys
from tbot_bot.support.utils_log import log_event

CONTROL_DIR = resolve_control_path()
LOGFILE = get_output_path("logs", "test_mode.log")
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_screener_integration.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
MAX_TEST_TIME = 90  # seconds per test

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_screener_integration", msg, logfile=LOGFILE)
    except Exception:
        pass

def timeout_handler(signum, frame):
    safe_print("[test_screener_integration] TIMEOUT")
    raise TimeoutError("test_screener_integration timed out")

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_screener_integration.py] Individual test flag not present. Exiting.")
        sys.exit(0)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_TEST_TIME)

class TestScreenerIntegration(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(MAX_TEST_TIME)

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        signal.alarm(0)

    def test_alpaca_screener(self):
        safe_print("[test_screener_integration] Alpaca screener test...")
        screener = AlpacaScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)
        safe_print("[test_screener_integration] Alpaca screener PASSED.")

    def test_finnhub_screener(self):
        safe_print("[test_screener_integration] Finnhub screener test...")
        screener = FinnhubScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)
        safe_print("[test_screener_integration] Finnhub screener PASSED.")

    def test_ibkr_screener(self):
        safe_print("[test_screener_integration] IBKR screener test...")
        screener = IBKRScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)
        safe_print("[test_screener_integration] IBKR screener PASSED.")

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_screener_integration] FINAL RESULT: {status}.")
    signal.alarm(0)

if __name__ == "__main__":
    run_test()
