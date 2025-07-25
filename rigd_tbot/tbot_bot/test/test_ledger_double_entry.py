# tbot_bot/test/test_ledger_double_entry.py
# Tests enforcement of double-entry posting and ledger balancing.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from tbot_bot.accounting.ledger.ledger_db import post_double_entry, get_db_path

class TestLedgerDoubleEntry(unittest.TestCase):
    def test_balanced_post(self):
        debit = {"account": "1000", "amount": 100, "side": "debit"}
        credit = {"account": "2000", "amount": 100, "side": "credit"}
        result = post_double_entry(debit, credit)
        self.assertTrue(result["balanced"])
        self.assertEqual(result["debit"]["amount"], result["credit"]["amount"])

    def test_unbalanced_post(self):
        debit = {"account": "1000", "amount": 100, "side": "debit"}
        credit = {"account": "2000", "amount": 50, "side": "credit"}
        with self.assertRaises(Exception):
            post_double_entry(debit, credit)

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
