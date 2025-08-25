# tbot_bot/test/test_ledger_reconciliation.py
# Tests reconciliation logging around broker → ledger sync.
# Ensures entries are written (when work happened) and that sync_run_id is consistent.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import time
from pathlib import Path

from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger
from tbot_bot.accounting.reconciliation_log import (
    ensure_reconciliation_log_initialized,
    get_reconciliation_entries,
)
from tbot_bot.support.path_resolver import resolve_control_path
from tbot_bot.support.utils_log import log_event

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_reconciliation.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg: str):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_reconciliation", msg)
    except Exception:
        pass


class TestLedgerReconciliation(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self._t0 = time.time()
        ensure_reconciliation_log_initialized()

    def tearDown(self):
        try:
            if Path(TEST_FLAG_PATH).exists():
                Path(TEST_FLAG_PATH).unlink()
        finally:
            elapsed = time.time() - self._t0
            if elapsed > MAX_TEST_TIME:
                safe_print(f"[test_ledger_reconciliation] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
                self.fail("Test timeout exceeded")

    def test_reconciliation_log_matched_and_skipped_sync_run_id_consistent(self):
        """
        Run a sync; verify reconciliation entries for this run have a single, consistent sync_run_id.
        If the run inserted rows or skipped older records, expect at least one reconciliation entry.
        """
        summary = sync_broker_ledger()
        self.assertIsInstance(summary, dict)
        sync_run_id = summary.get("sync_run_id")
        self.assertTrue(sync_run_id, "sync_broker_ledger should return a sync_run_id")

        # Fetch only entries for this run
        entries = get_reconciliation_entries(sync_run_id=sync_run_id, limit=5000)
        self.assertIsInstance(entries, list, "get_reconciliation_entries must return a list")

        # If anything meaningful happened, there should be reconciliation rows
        inserted = int(summary.get("inserted_rows", 0) or 0)
        skipped_older = int(summary.get("skipped_older", 0) or 0)

        if inserted > 0 or skipped_older > 0:
            self.assertGreater(len(entries), 0, "Expected reconciliation entries for this run")

        # All entries should carry the same sync_run_id
        for e in entries:
            self.assertEqual(
                e.get("sync_run_id"), sync_run_id,
                "Reconciliation entry has mismatched sync_run_id"
            )

        # Status sanity: current implementation allows statuses like 'matched' and coerces unknowns to 'rejected'
        # We don't require both to appear (depends on data), but if rows were inserted we expect at least one 'matched'
        if inserted > 0:
            has_matched = any((e.get("status") == "matched") for e in entries)
            self.assertTrue(has_matched, "Expected at least one 'matched' reconciliation entry when rows were inserted")

        # If older items were skipped, we expect at least one entry that is not 'matched'
        if skipped_older > 0 and entries:
            self.assertTrue(
                any(e.get("status") != "matched" for e in entries),
                "Expected at least one non-'matched' reconciliation entry when older items were skipped",
            )

        safe_print(
            f"[test_ledger_reconciliation] sync_run_id={sync_run_id} "
            f"inserted={inserted} skipped_older={skipped_older} entries={len(entries)}"
        )


def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_ledger_reconciliation] FINAL RESULT: {status}.")

if __name__ == "__main__":
    run_test()
