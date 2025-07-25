# tbot_bot/test/test_coa_mapping.py

import sys
import time
import pytest
from pathlib import Path
from tbot_bot.accounting.coa_utils import load_coa_metadata_and_accounts
from tbot_bot.accounting.coa_mapping_table import (
    load_mapping_table, assign_mapping, get_mapping_for_transaction, rollback_mapping_version
)
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event

MAX_TEST_TIME = 90  # seconds per test

# Ensure project root is in path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTROL_DIR = resolve_control_path()
LOGFILE = get_output_path("logs", "test_mode.log")
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_coa_mapping.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_coa_mapping", msg, logfile=LOGFILE)
    except Exception:
        pass

test_start = time.time()

def test_load_coa_metadata_and_accounts_structure():
    """
    Ensure COA metadata loader returns required structure and non-empty flat account list.
    """
    coa_data = load_coa_metadata_and_accounts()
    assert isinstance(coa_data, dict), "COA data should be a dictionary"
    assert "accounts_flat" in coa_data, "Missing 'accounts_flat' in COA data"
    accounts = coa_data["accounts_flat"]
    assert isinstance(accounts, list), "'accounts_flat' should be a list"
    assert accounts, "'accounts_flat' should not be empty in test environment"

    # Check basic account structure
    for acct in accounts:
        assert "code" in acct, "Missing 'code' in account"
        assert "name" in acct, "Missing 'name' in account"
        assert isinstance(acct["code"], str)
        assert isinstance(acct["name"], str)
    safe_print("test_load_coa_metadata_and_accounts_structure PASSED")

def test_no_duplicate_account_codes():
    """
    Ensure all account codes in the flat account list are unique.
    """
    coa_data = load_coa_metadata_and_accounts()
    codes = [acct["code"] for acct in coa_data["accounts_flat"]]
    assert len(set(codes)) == len(codes), "Duplicate account codes found in COA accounts"
    safe_print("test_no_duplicate_account_codes PASSED")

@pytest.mark.parametrize("field", ["accounts_flat", "accounts_tree", "metadata"])
def test_coa_data_contains_required_fields(field):
    """
    Test that core expected keys exist in the COA mapping data.
    """
    coa_data = load_coa_metadata_and_accounts()
    assert field in coa_data, f"COA mapping missing required field: {field}"
    safe_print(f"test_coa_data_contains_required_fields {field} PASSED")

def test_assign_and_get_mapping():
    """
    Test assigning a mapping rule and fetching it by transaction.
    """
    sample_rule = {
        "broker": "alpaca",
        "type": "buy",
        "subtype": "common",
        "description": "Buy Stock",
        "debit_account": "Assets:Brokerage Accounts – Equities:Cash",
        "credit_account": "Assets:Brokerage Accounts – Equities",
    }
    assign_mapping(sample_rule, user="test_user", reason="unit_test")
    table = load_mapping_table()
    found = get_mapping_for_transaction({
        "broker": "alpaca",
        "type": "buy",
        "subtype": "common",
        "description": "Buy Stock"
    }, table)
    assert found is not None, "Assigned mapping rule was not found"
    assert found["debit_account"] == sample_rule["debit_account"]
    assert found["credit_account"] == sample_rule["credit_account"]
    safe_print("test_assign_and_get_mapping PASSED")

def test_mapping_versioning_and_rollback():
    """
    Test mapping table versioning and rollback.
    """
    table_before = load_mapping_table()
    v_before = table_before.get("version", 1)
    # Assign a test mapping to trigger a new version
    assign_mapping({
        "broker": "alpaca",
        "type": "sell",
        "subtype": "common",
        "description": "Sell Stock",
        "debit_account": "Assets:Brokerage Accounts – Equities",
        "credit_account": "Assets:Brokerage Accounts – Equities:Cash"
    }, user="test_user", reason="version_test")
    table_after = load_mapping_table()
    v_after = table_after.get("version", 1)
    assert v_after > v_before, "Mapping version did not increment after assignment"
    # Roll back to previous version
    assert rollback_mapping_version(v_before), "Rollback to previous version failed"
    table_rolled = load_mapping_table()
    assert table_rolled.get("version", 1) > 0, "Mapping version after rollback invalid"
    safe_print("test_mapping_versioning_and_rollback PASSED")

def run_test():
    import pytest as _pytest
    ret = _pytest.main([__file__])
    status = "PASSED" if ret == 0 else "ERRORS"
    if (time.time() - test_start) > MAX_TEST_TIME:
        status = "TIMEOUT"
        safe_print(f"[test_coa_mapping] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
    if Path(TEST_FLAG_PATH).exists():
        Path(TEST_FLAG_PATH).unlink()
    safe_print(f"[test_coa_mapping] FINAL RESULT: {status}")

if __name__ == "__main__":
    run_test()
