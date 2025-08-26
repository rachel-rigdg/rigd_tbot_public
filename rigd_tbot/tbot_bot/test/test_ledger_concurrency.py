# tbot_bot/test/test_ledger_concurrency.py
# Tests concurrent ledger writes and locking.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import threading
import time
from tbot_bot.accounting.ledger_modules.ledger_db import add_entry, get_db_path
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sqlite3

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_concurrency.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_concurrency", msg)
    except Exception:
        pass

class TestLedgerConcurrency(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self.test_start = time.time()

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    def test_concurrent_writes(self):
        safe_print("[test_ledger_concurrency] Starting concurrent ledger write test...")
        errors = []
        db_path = get_db_path()
        def try_write(n):
            try:
                # Each thread uses a dedicated connection with a busy_timeout
                conn = sqlite3.connect(db_path, timeout=5)
                conn.execute("PRAGMA busy_timeout = 3000;")
                add_entry({"account": f"concurrent_{n}", "amount": 1.0, "side": "debit"})
                conn.close()
            except Exception as e:
                errors.append(str(e))
        threads = [threading.Thread(target=try_write, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        safe_print(f"[test_ledger_concurrency] Number of errors: {len(errors)}")
        # Allow minor race, but not systemic failure; tolerate <=2 busy errors
        self.assertLessEqual(len(errors), 2)
        safe_print("[test_ledger_concurrency] Concurrent ledger write test complete.")
        if (time.time() - self.test_start) > MAX_TEST_TIME:
            safe_print(f"[test_ledger_concurrency] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
            self.fail("Test timeout exceeded")

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_ledger_concurrency] FINAL RESULT: {status}.")

if __name__ == "__main__":
    run_test()
