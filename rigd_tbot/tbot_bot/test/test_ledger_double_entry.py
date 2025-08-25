# tbot_bot/test/test_ledger_double_entry.py
# Tests enforcement of double-entry posting and ledger balancing.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import time
import sqlite3
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from tbot_bot.support.path_resolver import resolve_control_path
from tbot_bot.support.utils_log import log_event

from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
    post_ledger_entries_double_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_core import get_conn

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_double_entry.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"


def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_double_entry", msg)
    except Exception:
        pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestLedgerDoubleEntry(unittest.TestCase):
    def setUp(self):
        # Preserve the existing flag-driven gating to avoid accidental runs in CI matrices.
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self.test_start = time.time()

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        if (time.time() - self.test_start) > MAX_TEST_TIME:
            safe_print(f"[test_ledger_double_entry] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
            self.fail("Test timeout exceeded")

    # --- helpers ---

    def _fetch_group_rows(self, group_id):
        with get_conn() as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM trades WHERE group_id = ?", (group_id,)).fetchall()

    # --- tests ---

    def test_balanced_post(self):
        """
        Two legs (debit/credit) with equal magnitudes must:
          - insert atomically
          - sum to 0.0000
          - respect sign rules (debit > 0, credit < 0)
          - carry the provided group_id
        """
        gid = f"test_gid_{int(time.time())}"
        debit = {
            "account": "Assets:Cash",
            "side": "debit",
            "total_value": 100.0,  # sign will be normalized (kept positive for debit)
            "trade_id": gid,
            "timestamp_utc": _utc_now_iso(),
            "strategy": "test",
        }
        credit = {
            "account": "Income:Sales",
            "side": "credit",
            "total_value": 100.0,  # sign will be normalized to negative for credit
            "trade_id": gid,
            "timestamp_utc": _utc_now_iso(),
            "strategy": "test",
        }

        res = post_ledger_entries_double_entry([debit, credit], group_id=gid)
        self.assertTrue(res.get("balanced", False))
        self.assertEqual(res.get("group_id"), gid)
        self.assertTrue(res.get("inserted_ids"), "No rows inserted")

        rows = self._fetch_group_rows(gid)
        self.assertEqual(len(rows), 2, "Expected exactly two rows for the group")

        totals = [Decimal(str(r["total_value"] or 0)).quantize(Decimal("0.0001")) for r in rows]
        self.assertEqual(sum(totals), Decimal("0.0000"), "Group should balance to zero")

        # Sign rules by side
        for r in rows:
            side = (r["side"] or "").lower()
            tv = Decimal(str(r["total_value"])).quantize(Decimal("0.0001"))
            if side == "debit":
                self.assertGreater(tv, Decimal("0"))
            elif side == "credit":
                self.assertLess(tv, Decimal("0"))

        # group_id propagation
        for r in rows:
            self.assertEqual(r["group_id"], gid)

        safe_print("[test_ledger_double_entry] test_balanced_post PASSED")

    def test_unbalanced_post_raises_and_no_orphans(self):
        """
        If magnitudes differ, the post must fail atomically (rollback) and leave no orphan rows.
        """
        gid = f"test_gid_unbalanced_{int(time.time())}"
        debit = {
            "account": "Assets:Cash",
            "side": "debit",
            "total_value": 100.0,
            "trade_id": gid,
            "timestamp_utc": _utc_now_iso(),
            "strategy": "test",
        }
        credit = {
            "account": "Income:Sales",
            "side": "credit",
            "total_value": 50.0,  # different magnitude -> imbalance
            "trade_id": gid,
            "timestamp_utc": _utc_now_iso(),
            "strategy": "test",
        }

        with self.assertRaises(Exception):
            post_ledger_entries_double_entry([debit, credit], group_id=gid)

        # Verify the batch was rolled back (no orphan rows for the failed group)
        rows = self._fetch_group_rows(gid)
        self.assertEqual(len(rows), 0, "Imbalanced post should not persist any rows")

        safe_print("[test_ledger_double_entry] test_unbalanced_post_raises_and_no_orphans PASSED")


def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_ledger_double_entry] FINAL RESULT: {status}.")


if __name__ == "__main__":
    run_test()
