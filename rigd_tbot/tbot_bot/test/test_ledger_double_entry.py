# tbot_bot/test/test_ledger_double_entry.py
# Tests enforcement of double-entry posting and ledger balancing.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import time
from tbot_bot.accounting.ledger_modules.ledger_db import post_double_entry, get_db_path
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_double_entry.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_double_entry", msg)
    except Exception:
        pass

class TestLedgerDoubleEntry(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self.test_start = time.time()

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        if (time.time() - self.test_start) > MAX_TEST_TIME:
            safe_print(f"[test_ledger_double_entry] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
            self.fail("Test timeout exceeded")

    def test_balanced_post(self):
        debit = {"account": "1000", "amount": 100.0, "side": "debit"}
        credit = {"account": "2000", "amount": 100.0, "side": "credit"}
        result = post_double_entry(debit, credit)
        self.assertTrue(result["balanced"])
        self.assertEqual(result["debit"]["amount"], result["credit"]["amount"])
        self.assertNotEqual(result["debit"]["account"], result["credit"]["account"])
        safe_print("[test_ledger_double_entry] test_balanced_post PASSED")

    def test_unbalanced_post(self):
        debit = {"account": "1000", "amount": 100.0, "side": "debit"}
        credit = {"account": "2000", "amount": 50.0, "side": "credit"}
        with self.assertRaises(Exception):
            post_double_entry(debit, credit)
        safe_print("[test_ledger_double_entry] test_unbalanced_post PASSED")

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_ledger_double_entry] FINAL RESULT: {status}.")

if __name__ == "__main__":
    run_test()
