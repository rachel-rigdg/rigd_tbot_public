# tbot_bot/test/test_broker_sync.py

import sys
import time
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger, _sanitize_entry
from tbot_bot.accounting.ledger_modules.ledger_db import get_db_path
from tbot_bot.accounting.ledger_modules.ledger_double_entry import validate_double_entry

MAX_TEST_TIME = 90  # seconds per test

def timed_pytest_run():
    pytest_args = ["-v", __file__]
    start = time.time()
    result = pytest.main(pytest_args)
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

def test_all_entries_are_dict_and_normalized():
    from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
    trades = fetch_all_trades(start_date="2025-01-01", end_date=None)
    cash_acts = fetch_cash_activity(start_date="2025-01-01", end_date=None)
    bad = [e for e in trades + cash_acts if not isinstance(e, dict)]
    if bad:
        print("[DEBUG] Non-dict broker entries:", bad)
    assert not bad, "Non-dict broker entries present"
    # Confirm all actions are in normalized allowed set or "other"
    valid_actions = {'long', 'short', 'put', 'inverse', 'call', 'assignment', 'exercise', 'expire', 'reorg', 'other'}
    for e in trades + cash_acts:
        if not isinstance(e, dict):
            continue
        action = e.get("action")
        assert action in valid_actions, f"Unmapped/invalid action: {action}, entry: {e}"

def test_sync_broker_ledger_runs_without_error():
    try:
        sync_broker_ledger()
    except AttributeError as e:
        print("[DEBUG] AttributeError caught!")
        import traceback
        traceback.print_exc()
        print("[DEBUG] If this is a 'str' object has no attribute 'get', hunt for non-dict entries in broker output.")
        pytest.fail(f"sync_broker_ledger AttributeError: {e}")
    except Exception as e:
        print("[DEBUG] Exception type:", type(e))
        print("[DEBUG] Exception value:", e)
        import traceback
        print("[DEBUG] Traceback:")
        traceback.print_exc()
        if "422" in str(e) or "Unprocessable Entity" in str(e):
            pytest.xfail(f"Alpaca adapter: known/fallback error (422) encountered: {e}")
        if "CHECK constraint failed: action IN" in str(e):
            pytest.fail(f"Ledger sync attempted to insert invalid action value. Mapping layer broken: {e}")
        pytest.fail(f"sync_broker_ledger raised an exception: {e}")

def test_sync_broker_ledger_idempotent(tmp_path):
    db_path = Path(get_db_path())
    db_backup = tmp_path / "ledger_backup.db"
    if db_path.exists():
        db_backup.write_bytes(db_path.read_bytes())
    try:
        sync_broker_ledger()
    except Exception as e:
        print("[DEBUG] Exception type (first sync):", type(e))
        print("[DEBUG] Exception value (first sync):", e)
        import traceback
        print("[DEBUG] Traceback (first sync):")
        traceback.print_exc()
        if "422" in str(e) or "Unprocessable Entity" in str(e):
            pytest.xfail(f"Alpaca adapter: known/fallback error (422) encountered: {e}")
        if "CHECK constraint failed: action IN" in str(e):
            pytest.fail(f"Ledger sync attempted to insert invalid action value. Mapping layer broken: {e}")
        pytest.fail(f"First sync_broker_ledger raised: {e}")
    if db_backup.exists():
        db_path.write_bytes(db_backup.read_bytes())
    try:
        sync_broker_ledger()
    except Exception as e:
        print("[DEBUG] Exception type (second sync):", type(e))
        print("[DEBUG] Exception value (second sync):", e)
        import traceback
        print("[DEBUG] Traceback (second sync):")
        traceback.print_exc()
        if "422" in str(e) or "Unprocessable Entity" in str(e):
            pytest.xfail(f"Alpaca adapter: known/fallback error (422) encountered: {e}")
        if "CHECK constraint failed: action IN" in str(e):
            pytest.fail(f"Ledger sync attempted to insert invalid action value. Mapping layer broken: {e}")
        pytest.fail(f"Second sync_broker_ledger raised: {e}")
    try:
        assert validate_double_entry() is True
    except Exception as e:
        print("[DEBUG] Exception in double entry validation:", e)
        pytest.fail(f"Ledger not double-entry balanced after repeated syncs: {e}")

def test_double_entry_posting_compliance():
    try:
        assert validate_double_entry() is True
    except Exception as e:
        print("[DEBUG] Exception in double entry validation:", e)
        pytest.fail(f"Ledger not double-entry balanced after sync: {e}")

def test_no_unmappable_actions_inserted():
    from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
    trades = fetch_all_trades(start_date="2025-01-01", end_date=None)
    cash_acts = fetch_cash_activity(start_date="2025-01-01", end_date=None)
    # This test asserts no unknown/unmappable action makes it into ledger pipeline
    allowed = {'long', 'short', 'put', 'inverse', 'call', 'assignment', 'exercise', 'expire', 'reorg', 'other'}
    for entry in trades + cash_acts:
        if not isinstance(entry, dict):
            continue
        action = entry.get("action")
        assert action in allowed, f"Disallowed/unmappable action value found: {action}, entry: {entry}"

if __name__ == "__main__":
    timed_pytest_run()
