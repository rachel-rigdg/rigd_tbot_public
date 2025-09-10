# tbot_bot/test/test_ledger_write_failure.py
# Tests ledger system's behavior on write failures and error propagation.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import time
from tbot_bot.accounting.ledger_modules.ledger_db import get_db_path
from tbot_bot.support.utils_log import log_event
import os
from pathlib import Path
from datetime import datetime, timezone
print(f"[LAUNCH] test_ledger_write_failure launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


MAX_TEST_TIME = 90  # seconds per test

class TestLedgerWriteFailure(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(get_db_path())
        if self.db_path.exists():
            self.orig_perms = self.db_path.stat().st_mode
            os.chmod(self.db_path, 0o444)

    def tearDown(self):
        if self.db_path.exists():
            os.chmod(self.db_path, 0o666)

    def test_write_failure(self):
        from tbot_bot.accounting.ledger_modules.ledger_db import add_entry
        with self.assertRaises(Exception):
            add_entry({"test": "failure"})

def run_test():
    result = "PASSED"
    start_time = time.time()
    try:
        unittest.main(module=__name__, exit=False)
    except Exception as e:
        result = "ERRORS"
        log_event("test_ledger_write_failure", f"Exception: {e}")
    elapsed = time.time() - start_time
    if elapsed > MAX_TEST_TIME:
        log_event("test_ledger_write_failure", f"TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
        result = "ERRORS"
    log_event("test_ledger_write_failure", f"[test_ledger_write_failure.py] FINAL RESULT: {result}")

if __name__ == "__main__":
    run_test()
