# tbot_bot/test/test_screener_integration.py
# Integration tests for screener modules using universe cache
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# STRICT: Test will only exercise /stock/symbol, /stock/profile2, /quote endpoints for Finnhub screener.

import unittest
from tbot_bot.screeners.alpaca_screener import AlpacaScreener
from tbot_bot.screeners.finnhub_screener import FinnhubScreener
from tbot_bot.screeners.ibkr_screener import IBKRScreener
from tbot_bot.support.path_resolver import resolve_control_path
from pathlib import Path
import sys

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_screener_integration.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_screener_integration.py] Individual test flag not present. Exiting.")
        sys.exit(0)

class TestScreenerIntegration(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

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
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
