# tbot_bot/test/test_ledger_reconciliation.py
# Tests reconciliation logic for detecting mismatches between ledger and COA.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from tbot_bot.accounting.ledger.ledger_db import reconcile_ledger_with_coa

class TestLedgerReconciliation(unittest.TestCase):
    def test_reconciliation(self):
        mismatches = reconcile_ledger_with_coa()
        self.assertIsInstance(mismatches, list)
        self.assertEqual(len(mismatches), 0)

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
