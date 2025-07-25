# tbot_bot/test/test_ledger_write_failure.py
# Tests ledger system's behavior on write failures and error propagation.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from tbot_bot.accounting.ledger.ledger_db import get_db_path
import os
from pathlib import Path

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
        from tbot_bot.accounting.ledger.ledger_db import add_entry
        with self.assertRaises(Exception):
            add_entry({"test": "failure"})

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
