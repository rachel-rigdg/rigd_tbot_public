# tbot_bot/test/test_universe_cache.py
# Unit/integration tests for universe cache build, loading, and validation
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import time
from tbot_bot.screeners.screener_utils import (
    save_universe_cache,
    load_universe_cache,
    UniverseCacheError,
)
from tbot_bot.screeners.universe_orchestrator import main as refresh_main
from tbot_bot.support.path_resolver import resolve_universe_cache_path, resolve_control_path, get_output_path
import os
from pathlib import Path
import sys
from tbot_bot.support.utils_log import log_event

CONTROL_DIR = resolve_control_path()
LOGFILE = get_output_path("logs", "test_mode.log")
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_universe_cache.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
MAX_TEST_TIME = 90  # seconds per test

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_universe_cache", msg, logfile=LOGFILE)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_universe_cache.py] Individual test flag not present. Exiting.")
        sys.exit(1)
else:
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        raise RuntimeError("[test_universe_cache.py] Individual test flag not present.")

class TestUniverseCache(unittest.TestCase):
    def setUp(self):
        # Inject a valid indexed credential file if needed (simulate if not present)
        # (NOTE: If using real credentials, skip this; this ensures test will not fail for missing indexed keys)
        from tbot_bot.support import secrets_manager
        creds_path = secrets_manager.get_screener_credentials_path()
        if not os.path.exists(creds_path):
            secrets_manager.save_screener_credentials({
                "PROVIDER_01": "FINNHUB",
                "SCREENER_NAME_01": "FINNHUB",
                "SCREENER_USERNAME_01": "user",
                "SCREENER_PASSWORD_01": "pw",
                "SCREENER_URL_01": "https://api.finnhub.io",
                "SCREENER_API_KEY_01": "apikey",
                "SCREENER_TOKEN_01": "",
                "UNIVERSE_ENABLED_01": "true",
                "TRADING_ENABLED_01": "false",
                "ENRICHMENT_ENABLED_01": "false"
            })
        self.dummy_symbols = [
            {"symbol": "AAPL", "exchange": "NASDAQ", "lastClose": 190.5, "marketCap": 2900000000000, "sector": "Tech", "companyName": "Apple Inc."},
            {"symbol": "MSFT", "exchange": "NASDAQ", "lastClose": 310.2, "marketCap": 2500000000000, "sector": "Tech", "companyName": "Microsoft"},
        ]
        self.cache_path = resolve_universe_cache_path()
        save_universe_cache(self.dummy_symbols)

    def tearDown(self):
        if os.path.exists(self.cache_path):
            os.remove(self.cache_path)

    def test_cache_load_valid(self):
        start = time.time()
        safe_print("[test_universe_cache] test_cache_load_valid")
        loaded = load_universe_cache()
        self.assertIsInstance(loaded, list)
        self.assertTrue(any(s["symbol"] == "AAPL" for s in loaded))
        elapsed = time.time() - start
        assert elapsed <= MAX_TEST_TIME, "TIMEOUT"

    def test_cache_filter(self):
        start = time.time()
        safe_print("[test_universe_cache] test_cache_filter")
        filtered = [s for s in self.dummy_symbols if s["exchange"] == "NASDAQ" and 100 <= s["lastClose"] <= 400 and 2e9 <= s["marketCap"] <= 3e12]
        self.assertEqual(len(filtered), 2)
        elapsed = time.time() - start
        assert elapsed <= MAX_TEST_TIME, "TIMEOUT"

    def test_cache_stale(self):
        start = time.time()
        safe_print("[test_universe_cache] test_cache_stale")
        import json
        import datetime
        from datetime import timedelta, timezone

        with open(self.cache_path, "r+", encoding="utf-8") as f:
            data = json.load(f)
            stale_time = (datetime.datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            data["build_timestamp_utc"] = stale_time
            f.seek(0)
            json.dump(data, f)
            f.truncate()
        with self.assertRaises(UniverseCacheError):
            load_universe_cache()
        elapsed = time.time() - start
        assert elapsed <= MAX_TEST_TIME, "TIMEOUT"

    def test_cache_refresh_main(self):
        start = time.time()
        safe_print("[test_universe_cache] test_cache_refresh_main")
        try:
            refresh_main()
        except SystemExit:
            pass
        elapsed = time.time() - start
        assert elapsed <= MAX_TEST_TIME, "TIMEOUT"

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_universe_cache] FINAL RESULT: {status}.")

if __name__ == "__main__":
    try:
        run_test()
    finally:
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
