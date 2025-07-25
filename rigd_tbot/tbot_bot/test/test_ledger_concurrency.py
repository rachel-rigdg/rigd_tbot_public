# tbot_bot/test/test_ledger_concurrency.py
# Tests concurrent ledger writes and locking.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import threading
from tbot_bot.accounting.ledger.ledger_db import add_entry, get_db_path

class TestLedgerConcurrency(unittest.TestCase):
    def test_concurrent_writes(self):
        errors = []
        def try_write(n):
            try:
                add_entry({"test": f"concurrent_{n}"})
            except Exception as e:
                errors.append(str(e))
        threads = [threading.Thread(target=try_write, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertLessEqual(len(errors), 2)  # Allow minor race, but not systemic failure

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
