# tbot_bot/test/test_ledger_corruption.py
# Tests ledger system's behavior when the database is corrupted or unreadable.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import os
from pathlib import Path
from tbot_bot.accounting.ledger.ledger_db import get_db_path

class TestLedgerCorruption(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(get_db_path())
        if self.db_path.exists():
            with open(self.db_path, "wb") as f:
                f.write(b"CORRUPTEDDATA")

    def test_corruption_detection(self):
        from tbot_bot.accounting.ledger.ledger_db import validate_ledger_schema
        with self.assertRaises(Exception):
            validate_ledger_schema()

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
