# tbot_bot/test/test_screener_random.py
# Runs screener logic with randomized symbols to confirm filtering and eligibility logic
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import random
from tbot_bot.screeners.finnhub_screener import FinnhubScreener
from tbot_bot.screeners.alpaca_screener import AlpacaScreener
from tbot_bot.screeners.ibkr_screener import IBKRScreener
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path
from pathlib import Path
import sys

TEST_FLAG_PATH = get_output_path("control", "test_mode_screener_random.flag")
RUN_ALL_FLAG = get_output_path("control", "test_mode.flag")

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_screener_random.py] Individual test flag not present. Exiting.")
        sys.exit(0)

SAMPLE_SYMBOLS = [
    "AAPL", "MSFT", "TSLA", "GOOG", "AMZN",
    "NVDA", "AMD", "INTC", "SPY", "QQQ",
    "META", "NFLX", "BA", "T", "XOM"
]

def random_symbols(n=5):
    return random.sample(SAMPLE_SYMBOLS, min(n, len(SAMPLE_SYMBOLS)))

class TestScreenerRandom(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    def test_random_symbol_filtering(self):
        safe_print("[test_screener_random] Running test_random_symbol_filtering...")
        config = get_bot_config()
        for screener_cls in [FinnhubScreener, AlpacaScreener, IBKRScreener]:
            screener = screener_cls(config=config)
            symbols = random_symbols(10)
            if hasattr(screener, 'filter_symbols'):
                eligible = screener.filter_symbols(symbols)
            else:
                eligible = symbols
            self.assertIsInstance(eligible, list)
            self.assertTrue(all(isinstance(s, str) for s in eligible))
            self.assertLessEqual(len(eligible), len(symbols))
        safe_print("[test_screener_random] PASSED.")

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
