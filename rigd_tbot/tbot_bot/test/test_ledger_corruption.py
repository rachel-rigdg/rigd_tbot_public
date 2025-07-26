# tbot_bot/test/test_ledger_corruption.py
# Tests ledger system's behavior when the database is corrupted or unreadable.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import os
import time
from pathlib import Path
from tbot_bot.accounting.ledger_modules.ledger_db import get_db_path
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_corruption.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_corruption", msg)
    except Exception:
        pass

class TestLedgerCorruption(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self.test_start = time.time()
        self.db_path = Path(get_db_path())
        if self.db_path.exists():
            with open(self.db_path, "wb") as f:
                f.write(b"CORRUPTEDDATA")

    def tearDown(self):
        # Optionally restore a valid database or remove corrupted one
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    def test_corruption_detection(self):
        from tbot_bot.accounting.ledger_modules.ledger_db import validate_ledger_schema
        safe_print("[test_ledger_corruption] Validating schema on corrupted db...")
        try:
            validate_ledger_schema()
        except Exception:
            safe_print("[test_ledger_corruption] Corruption detected as expected.")
            return
        self.fail("Corruption was not detected by validate_ledger_schema")
        if (time.time() - self.test_start) > MAX_TEST_TIME:
            safe_print(f"[test_ledger_corruption] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
            self.fail("Test timeout exceeded")

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_ledger_corruption] FINAL RESULT: {status}.")

if __name__ == "__main__":
    run_test()
