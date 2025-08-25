# tbot_bot/test/test_ledger_write_failure.py
# Tests ledger system's behavior on write failures and error propagation.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import time
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from unittest import mock
import sqlite3

from tbot_bot.accounting.ledger_modules.ledger_core import get_conn
from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
    post_ledger_entries_double_entry,
    validate_double_entry,
)
from tbot_bot.support.utils_log import log_event


MAX_TEST_TIME = 90  # seconds per test


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class _ConnProxy:
    """
    Wraps a real sqlite3 connection to simulate a failure on the second INSERT INTO trades.
    All non-insert statements are delegated.
    """
    def __init__(self, real_conn: sqlite3.Connection):
        self._c = real_conn
        self._insert_count = 0

    def execute(self, sql, params=()):
        # Let selects/dml other than INSERT INTO trades pass through
        if isinstance(sql, str) and "INSERT INTO trades" in sql:
            self._insert_count += 1
            if self._insert_count == 2:
                # Simulate a mid-batch write failure -> should trigger rollback in tx_context
                raise sqlite3.OperationalError("Simulated write failure on second INSERT")
        return self._c.execute(sql, params)

    # Delegate other attrs used by the writer
    def __getattr__(self, name):
        return getattr(self._c, name)


class TestLedgerWriteFailure(unittest.TestCase):
    def setUp(self):
        self._t0 = time.time()

    def tearDown(self):
        elapsed = time.time() - self._t0
        if elapsed > MAX_TEST_TIME:
            log_event("test_ledger_write_failure", f"TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
            self.fail("Test timeout exceeded")

    def test_atomic_rollback_on_mid_batch_failure(self):
        """
        Prepare a balanced two-leg batch (pre-split). Fail the second insert.
        Expect: exception, 0 rows with that group_id, and global double-entry still validates.
        """
        gid = f"wf_{uuid.uuid4()}"
        tid = gid
        ts = _utc_now()

        debit = {
            "trade_id": tid,
            "group_id": gid,
            "account": "Assets:Test:Cash",
            "side": "debit",
            "total_value": 10.00,   # positive for debit
            "timestamp_utc": ts,
            "symbol": "WFTEST",
            "action": "other",
        }
        credit = {
            "trade_id": tid,
            "group_id": gid,
            "account": "Income:Test",
            "side": "credit",
            "total_value": -10.00,  # negative for credit
            "timestamp_utc": ts,
            "symbol": "WFTEST",
            "action": "other",
        }

        # Patch the tx_context used *inside* post_ledger_entries_double_entry to inject our failing connection
        import tbot_bot.accounting.ledger_modules.ledger_double_entry as lde

        @contextmanager
        def failing_tx_context():
            with get_conn() as real:
                proxy = _ConnProxy(real)
                try:
                    # begin transaction explicitly to ensure rollback/commit behavior is exercised
                    real.execute("BEGIN")
                    yield proxy
                    real.commit()
                except Exception:
                    real.rollback()
                    raise

        with mock.patch.object(lde, "tx_context", failing_tx_context):
            with self.assertRaises(sqlite3.OperationalError):
                post_ledger_entries_double_entry([debit, credit], group_id=gid)

        # Verify rollback: no rows with this group_id exist
        with get_conn() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM trades WHERE group_id = ?", (gid,)).fetchone()[0]
            self.assertEqual(cnt, 0, "Partial group rows found after simulated write failure (rollback broken)")

        # Global double-entry integrity should still hold
        self.assertTrue(validate_double_entry())

        # (Optional) You can add an audit emission here if write-failure events are audited in your stack.
        # For now, we simply log the outcome of the test for CI traceability.
        log_event("test_ledger_write_failure", "Rollback verified; no partial groups persisted.")

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
