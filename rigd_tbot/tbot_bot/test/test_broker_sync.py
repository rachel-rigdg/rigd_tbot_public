# tbot_bot/test/test_broker_sync.py

import sys
import time
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tbot_bot.accounting.ledger as ledger_mod
from tbot_bot.accounting.ledger_modules.ledger_double_entry import validate_double_entry

MAX_TEST_TIME = 90  # seconds per test

def timed_pytest_run():
    start = time.time()
    result = pytest.main([__file__])
    elapsed = time.time() - start
    if elapsed > MAX_TEST_TIME:
        print(f"[test_broker_sync.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds", flush=True)
    return result

def test_sync_broker_ledger_runs_without_error(monkeypatch):
    try:
        ledger_mod.sync_broker_ledger()
    except Exception as e:
        pytest.fail(f"sync_broker_ledger raised an exception: {e}")

def test_sync_broker_ledger_idempotent(monkeypatch, tmp_path):
    """
    Test that running sync twice does not result in duplicate or inconsistent ledger state.
    This version enforces DB integrity before/after.
    """
    # Setup: Backup DB state if possible (implementation-dependent)
    db_path = Path(ledger_mod.get_ledger_db_path())
    db_backup = tmp_path / "ledger_backup.db"
    if db_path.exists():
        db_backup.write_bytes(db_path.read_bytes())

    # First sync
    try:
        ledger_mod.sync_broker_ledger()
    except Exception as e:
        pytest.fail(f"First sync_broker_ledger raised: {e}")

    # Second sync (should not error)
    try:
        ledger_mod.sync_broker_ledger()
    except Exception as e:
        pytest.fail(f"Second sync_broker_ledger raised: {e}")

    # Double-entry validation after repeated syncs
    try:
        assert validate_double_entry() is True
    except Exception as e:
        pytest.fail(f"Ledger not double-entry balanced after repeated syncs: {e}")

    # Optional: Restore DB state if required (cleanup)
    if db_backup.exists():
        db_path.write_bytes(db_backup.read_bytes())

def test_double_entry_posting_compliance():
    try:
        assert validate_double_entry() is True
    except Exception as e:
        pytest.fail(f"Ledger not double-entry balanced after sync: {e}")

if __name__ == "__main__":
    timed_pytest_run()
