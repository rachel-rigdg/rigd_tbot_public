# tbot_bot/test/test_coa_mapping.py

import sys
import pytest
from pathlib import Path

# Ensure project root is in path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tbot_web.support.utils_coa_web import load_coa_metadata_and_accounts

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

def test_no_duplicate_account_codes():
    """
    Ensure all account codes in the flat account list are unique.
    """
    coa_data = load_coa_metadata_and_accounts()
    codes = [acct["code"] for acct in coa_data["accounts_flat"]]
    assert len(set(codes)) == len(codes), "Duplicate account codes found in COA accounts"

@pytest.mark.parametrize("field", ["accounts_flat", "accounts_tree", "metadata"])
def test_coa_data_contains_required_fields(field):
    """
    Test that core expected keys exist in the COA mapping data.
    """
    coa_data = load_coa_metadata_and_accounts()
    assert field in coa_data, f"COA mapping missing required field: {field}"
