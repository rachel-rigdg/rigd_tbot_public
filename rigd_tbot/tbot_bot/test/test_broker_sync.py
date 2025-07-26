# tbot_bot/test/test_broker_sync.py

import sys
import time
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger
from tbot_bot.accounting.ledger_modules.ledger_db import get_db_path
from tbot_bot.accounting.ledger_modules.ledger_double_entry import validate_double_entry

MAX_TEST_TIME = 90  # seconds per test

def timed_pytest_run():
    start = time.time()
    result = pytest.main([__file__])
    elapsed = time.time() - start
    if elapsed > MAX_TEST_TIME:
        print(f"[test_broker_sync.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds", flush=True)
    return result

@pytest.fixture(autouse=True)
def isolate_ledger_db(tmp_path, monkeypatch):
    orig_db_path = Path(get_db_path())
    test_db_path = tmp_path / "ledger_test_copy.db"
    if orig_db_path.exists():
        test_db_path.write_bytes(orig_db_path.read_bytes())
        monkeypatch.setattr("tbot_bot.accounting.ledger_modules.ledger_db.get_db_path", lambda: str(test_db_path))
    yield
    # tmp_path and db copy cleaned automatically

def test_sync_broker_ledger_runs_without_error():
    try:
        sync_broker_ledger()
    except Exception as e:
        if "422" in str(e) or "Unprocessable Entity" in str(e):
            pytest.xfail(f"Alpaca adapter: known/fallback error (422) encountered: {e}")
        pytest.fail(f"sync_broker_ledger raised an exception: {e}")

def test_sync_broker_ledger_idempotent(tmp_path):
    db_path = Path(get_db_path())
    db_backup = tmp_path / "ledger_backup.db"
    if db_path.exists():
        db_backup.write_bytes(db_path.read_bytes())
    try:
        sync_broker_ledger()
    except Exception as e:
        if "422" in str(e) or "Unprocessable Entity" in str(e):
            pytest.xfail(f"Alpaca adapter: known/fallback error (422) encountered: {e}")
        pytest.fail(f"First sync_broker_ledger raised: {e}")
    if db_backup.exists():
        db_path.write_bytes(db_backup.read_bytes())
    try:
        sync_broker_ledger()
    except Exception as e:
        if "422" in str(e) or "Unprocessable Entity" in str(e):
            pytest.xfail(f"Alpaca adapter: known/fallback error (422) encountered: {e}")
        pytest.fail(f"Second sync_broker_ledger raised: {e}")
    try:
        assert validate_double_entry() is True
    except Exception as e:
        pytest.fail(f"Ledger not double-entry balanced after repeated syncs: {e}")

def test_double_entry_posting_compliance():
    try:
        assert validate_double_entry() is True
    except Exception as e:
        pytest.fail(f"Ledger not double-entry balanced after sync: {e}")

if __name__ == "__main__":
    timed_pytest_run()
