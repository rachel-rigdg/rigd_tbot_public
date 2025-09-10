# tbot_bot/test/test_ledger_migration.py
# Tests schema migration and versioning.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import time
from tbot_bot.accounting.ledger_modules.ledger_db import run_schema_migration, get_db_path
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path, resolve_ledger_schema_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
from datetime import datetime, timezone
print(f"[LAUNCH] test_ledger_migration launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_migration.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_migration", msg)
    except Exception:
        pass

class TestLedgerMigration(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self.test_start = time.time()

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        if (time.time() - self.test_start) > MAX_TEST_TIME:
            safe_print(f"[test_ledger_migration] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
            self.fail("Test timeout exceeded")

    def test_migration(self):
        migration_sql_path = resolve_ledger_schema_path()
        result = run_schema_migration(migration_sql_path)
        # Accept either a dict with 'migrated': True, or None if no-op
        if isinstance(result, dict):
            self.assertIn("migrated", result)
            self.assertTrue(result["migrated"])
        safe_print("[test_ledger_migration] test_migration PASSED")

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_ledger_migration] FINAL RESULT: {status}.")

if __name__ == "__main__":
    run_test()
