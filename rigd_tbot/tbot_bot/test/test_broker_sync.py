# tbot_bot/test/test_broker_sync.py

import sys
import time
import pytest
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger, _sanitize_entry
from tbot_bot.accounting.ledger_modules.ledger_db import get_db_path
from tbot_bot.accounting.ledger_modules.ledger_double_entry import validate_double_entry
from tbot_bot.accounting.ledger_modules import ledger_compliance_filter, ledger_deduplication

MAX_TEST_TIME = 90  # seconds per test

def timed_pytest_run():
    pytest_args = ["-v", __file__]
    start = time.time()
    try:
        result = pytest.main(pytest_args)
    except Exception as e:
        print(f"[test_broker_sync.py] Pytest run error: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    elapsed = time.time() - start
    if elapsed > MAX_TEST_TIME:
        print(f"[test_broker_sync.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds", flush=True)
    return result

@pytest.fixture(autouse=True)
def isolate_ledger_db(tmp_path, monkeypatch):
    orig_db_path = Path(get_db_path())
    test_db_path = tmp_path / "ledger_test_copy.db"
    if orig_db_path.exists():
        shutil.copyfile(orig_db_path, test_db_path)
        monkeypatch.setattr("tbot_bot.accounting.ledger_modules.ledger_db.get_db_path", lambda: str(test_db_path))
    yield
    # tmp_path and db copy cleaned automatically

def test_all_entries_are_dict_and_normalized():
    from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
    try:
        trades = fetch_all_trades(start_date="2025-01-01", end_date=None)
        cash_acts = fetch_cash_activity(start_date="2025-01-01", end_date=None)
    except Exception as e:
        print("[DEBUG] Error fetching broker data:", e)
        import traceback
        traceback.print_exc()
        pytest.fail(f"Broker fetch failed: {e}")
    bad = [e for e in trades + cash_acts if not isinstance(e, dict)]
    if bad:
        print("[DEBUG] Non-dict broker entries:", bad)
    assert not bad, "Non-dict broker entries present"
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
        print("[DEBUG] Exception in sync_broker_ledger_runs_without_error:", e)
        import traceback
        traceback.print_exc()
        pytest.fail(f"sync_broker_ledger raised: {type(e).__name__}: {e}")

def test_sync_broker_ledger_idempotent(tmp_path):
    orig_db_path = Path(get_db_path())
    test_db_path = tmp_path / "ledger_test_copy.db"
    if orig_db_path.exists():
        shutil.copyfile(orig_db_path, test_db_path)
    else:
        pytest.skip("Original ledger DB does not exist for duplication.")

    import tbot_bot.accounting.ledger_modules.ledger_db as ledger_db_module
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ledger_db_module, "get_db_path", lambda: str(test_db_path))

    try:
        # Fetch trades and cash activities
        from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
        trades = fetch_all_trades(start_date="2025-01-01", end_date=None)
        cash_acts = fetch_cash_activity(start_date="2025-01-01", end_date=None)
        # Apply compliance filter and deduplication before sync
        all_entries = trades + cash_acts
        filtered = ledger_compliance_filter.filter_valid_entries(all_entries)
        deduped = ledger_deduplication.deduplicate_entries(filtered)

        # Sanitize entries before posting
        sanitized_entries = [_sanitize_entry(e) for e in deduped]

        # Post filtered and deduplicated entries using double-entry post
        from tbot_bot.accounting.ledger_modules.ledger_double_entry import post_double_entry
        post_double_entry(sanitized_entries)

        sync_broker_ledger()
    except Exception as e:
        print("[DEBUG] Exception type (first sync):", type(e))
        print("[DEBUG] Exception value (first sync):", e)
        import traceback
        traceback.print_exc()
        pytest.fail(f"First sync_broker_ledger raised: {type(e).__name__}: {e}")

    try:
        sync_broker_ledger()
    except Exception as e:
        print("[DEBUG] Exception type (second sync):", type(e))
        print("[DEBUG] Exception value (second sync):", e)
        import traceback
        traceback.print_exc()
        pytest.fail(f"Second sync_broker_ledger raised: {type(e).__name__}: {e}")

    try:
        assert validate_double_entry() is True
    except Exception as e:
        print("[DEBUG] Exception in double entry validation:", e)
        import traceback
        traceback.print_exc()
        pytest.fail(f"Ledger not double-entry balanced after repeated syncs: {type(e).__name__}: {e}")

    monkeypatch.undo()

def test_double_entry_posting_compliance():
    try:
        assert validate_double_entry() is True
    except Exception as e:
        print("[DEBUG] Exception in double entry validation:", e)
        import traceback
        traceback.print_exc()
        pytest.fail(f"Ledger not double-entry balanced after sync: {type(e).__name__}: {e}")

def test_no_unmappable_actions_inserted():
    from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
    try:
        trades = fetch_all_trades(start_date="2025-01-01", end_date=None)
        cash_acts = fetch_cash_activity(start_date="2025-01-01", end_date=None)
    except Exception as e:
        print("[DEBUG] Error fetching broker data:", e)
        import traceback
        traceback.print_exc()
        pytest.fail(f"Broker fetch failed: {e}")
    allowed = {'long', 'short', 'put', 'inverse', 'call', 'assignment', 'exercise', 'expire', 'reorg', 'other'}
    for entry in trades + cash_acts:
        if not isinstance(entry, dict):
            continue
        action = entry.get("action")
        assert action in allowed, f"Disallowed/unmappable action value found: {action}, entry: {entry}"

if __name__ == "__main__":
    try:
        timed_pytest_run()
    except Exception as e:
        print(f"[test_broker_sync.py] Test runner error: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
