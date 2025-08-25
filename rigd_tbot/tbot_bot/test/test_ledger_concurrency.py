# tbot_bot/test/test_ledger_concurrency.py
# Tests concurrent ledger writes and locking.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import uuid

from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
    post_ledger_entries_double_entry,
    validate_double_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_deduplication import install_unique_guards
from tbot_bot.accounting.ledger_modules.ledger_core import get_conn
from tbot_bot.support.path_resolver import resolve_control_path
from tbot_bot.support.utils_log import log_event

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_concurrency.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"


def safe_print(msg: str):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_concurrency", msg)
    except Exception:
        pass


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class TestLedgerConcurrency(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self._t0 = time.time()
        # Ensure DB guards exist before racing inserts
        try:
            install_unique_guards()
        except Exception:
            # Best-effort; not fatal if already present
            pass

    def tearDown(self):
        try:
            if Path(TEST_FLAG_PATH).exists():
                Path(TEST_FLAG_PATH).unlink()
        finally:
            elapsed = time.time() - self._t0
            if elapsed > MAX_TEST_TIME:
                safe_print(f"[test_ledger_concurrency] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
                self.fail("Test timeout exceeded")

    # ------------------------------
    # Helpers
    # ------------------------------

    def _post_balanced_group(self, trade_id: str, group_id: str, amount: float = 1.00):
        """
        Post a pre-split, balanced (debit/credit) group atomically using the public double-entry API.
        Avoids mapping so the test doesn't depend on mapping table state.
        """
        ts = _utc_now()
        # Representative accounts; schema doesn't validate account values here
        debit = {
            "trade_id": trade_id,
            "group_id": group_id,
            "account": "Assets:Test:Cash",
            "side": "debit",
            "total_value": amount,
            "timestamp_utc": ts,
            "symbol": "TEST",
            "action": "other",
        }
        credit = {
            "trade_id": trade_id,
            "group
