# tbot_bot/test/test_ledger_migration.py
# Tests schema migration and versioning.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from tbot_bot.accounting.ledger.ledger_db import run_schema_migration, get_db_path

class TestLedgerMigration(unittest.TestCase):
    def test_migration(self):
        result = run_schema_migration()
        self.assertIn("migrated", result)
        self.assertTrue(result["migrated"])

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
