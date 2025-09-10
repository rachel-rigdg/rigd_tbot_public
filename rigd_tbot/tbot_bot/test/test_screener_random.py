# tbot_bot/test/test_screener_random.py
# Runs screener logic with randomized symbols to confirm filtering and eligibility logic
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import random
import signal
from tbot_bot.screeners.screeners.alpaca_screener import AlpacaScreener
from tbot_bot.screeners.screeners.finnhub_screener import FinnhubScreener
from tbot_bot.screeners.screeners.ibkr_screener import IBKRScreener
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys
from datetime import datetime, timezone
print(f"[LAUNCH] test_screener_random launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


CONTROL_DIR = resolve_control_path()
LOGFILE = get_output_path("logs", "test_mode.log")
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_screener_random.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
MAX_TEST_TIME = 90  # seconds per test

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_screener_random", msg, logfile=LOGFILE)
    except Exception:
        pass

def timeout_handler(signum, frame):
    safe_print("[test_screener_random] TIMEOUT")
    raise TimeoutError("test_screener_random timed out")

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_screener_random.py] Individual test flag not present. Exiting.")
        sys.exit(0)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_TEST_TIME)

SAMPLE_SYMBOLS = [
    "AAPL", "MSFT", "TSLA", "GOOG", "AMZN",
    "NVDA", "AMD", "INTC", "SPY", "QQQ",
    "META", "NFLX", "BA", "T", "XOM"
]

def random_symbols(n=5):
    return random.sample(SAMPLE_SYMBOLS, min(n, len(SAMPLE_SYMBOLS)))

def get_enabled_screeners():
    creds = load_screener_credentials()
    enabled = []
    # Generic format: PROVIDER_xx with TRADING_ENABLED_xx == TRUE
    for key, val in creds.items():
        if key.startswith("PROVIDER_"):
            idx = key.split("_")[-1]
            enabled_flag = creds.get(f"TRADING_ENABLED_{idx}", "false").upper() == "TRUE"
            provider = val.strip().upper()
            if enabled_flag:
                if provider == "ALPACA":
                    enabled.append(AlpacaScreener)
                elif provider == "FINNHUB":
                    enabled.append(FinnhubScreener)
                elif provider == "IBKR":
                    enabled.append(IBKRScreener)
    return enabled

class TestScreenerRandom(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(MAX_TEST_TIME)

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        signal.alarm(0)

    def test_random_symbol_filtering(self):
        safe_print("[test_screener_random] Running test_random_symbol_filtering...")
        config = get_bot_config()
        enabled_screeners = get_enabled_screeners()
        if not enabled_screeners:
            safe_print("[test_screener_random] No screeners enabled in credentials, skipping.")
            self.skipTest("No screeners enabled in credentials.")
        for screener_cls in enabled_screeners:
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
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_screener_random] FINAL RESULT: {status}.")
    signal.alarm(0)

if __name__ == "__main__":
    run_test()
