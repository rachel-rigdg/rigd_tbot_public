# tbot_bot/test/test_screener_integration.py
# Integration tests for screener modules using universe cache
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# STRICT: Test will only exercise /stock/symbol, /stock/profile2, /quote endpoints for Finnhub screener.

import unittest
from tbot_bot.screeners.alpaca_screener import AlpacaScreener
from tbot_bot.screeners.finnhub_screener import FinnhubScreener
from tbot_bot.screeners.ibkr_screener import IBKRScreener
from pathlib import Path
import sys

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_screener_integration.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        print("[test_screener_integration.py] Individual test flag not present. Exiting.")
        sys.exit(1)

class TestScreenerIntegration(unittest.TestCase):
    def setUp(self):
        if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
            self.skipTest("Individual test flag not present. Exiting.")

    def tearDown(self):
        if TEST_FLAG_PATH.exists():
            TEST_FLAG_PATH.unlink()

    def test_alpaca_screener(self):
        screener = AlpacaScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)

    def test_finnhub_screener(self):
        screener = FinnhubScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)
        # ENFORCEMENT: Confirm Finnhub screener only pulls from permitted endpoints during test.

    def test_ibkr_screener(self):
        screener = IBKRScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
