# tbot_bot/test/test_universe_cache.py
# Unit/integration tests for universe cache build, loading, and validation
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from tbot_bot.screeners.screener_utils import (
    save_universe_cache,
    load_universe_cache,
    filter_symbols,
    UniverseCacheError,
)
from tbot_bot.screeners.symbol_universe_refresh import main as refresh_main
from tbot_bot.support.path_resolver import resolve_universe_cache_path, get_output_path
import os
from pathlib import Path
import sys

TEST_FLAG_PATH = get_output_path("control", "test_mode_universe_cache.flag")
RUN_ALL_FLAG = get_output_path("control", "test_mode.flag")

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        print("[test_universe_cache.py] Individual test flag not present. Exiting.")
        sys.exit(1)
else:
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        raise RuntimeError("[test_universe_cache.py] Individual test flag not present.")

class TestUniverseCache(unittest.TestCase):
    def setUp(self):
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
        loaded = load_universe_cache()
        self.assertIsInstance(loaded, list)
        self.assertTrue(any(s["symbol"] == "AAPL" for s in loaded))

    def test_cache_filter(self):
        filtered = filter_symbols(
            self.dummy_symbols, ["NASDAQ"], 100, 400, 2e9, 3e12, None, None
        )
        self.assertEqual(len(filtered), 2)

    def test_cache_stale(self):
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

    def test_cache_refresh_main(self):
        try:
            refresh_main()
        except SystemExit:
            pass

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    try:
        run_test()
    finally:
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
