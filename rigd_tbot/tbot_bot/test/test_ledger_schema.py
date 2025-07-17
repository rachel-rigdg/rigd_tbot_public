# tbot_bot/test/test_ledger_schema.py
# Tests that new ledgers match COA/schema and double-entry enforcement
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
from tbot_bot.accounting.ledger_utils import validate_ledger_schema
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from pathlib import Path
import sys

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_ledger_schema.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        print("[test_ledger_schema.py] Individual test flag not present. Exiting.")
        sys.exit(1)

def test_ledger_schema_validation():
    """
    Validates that the ledger DB conforms to schema and double-entry rules.
    Does not launch or supervise any persistent process.
    """
    try:
        result = validate_ledger_schema()
    except Exception as e:
        pytest.fail(f"Ledger schema validation failed: {e}")
    assert result is True, "Ledger schema is not valid or compliant."

def run_test():
    import pytest as _pytest
    _pytest.main([__file__])
    if TEST_FLAG_PATH.exists():
        TEST_FLAG_PATH.unlink()

if __name__ == "__main__":
    run_test()
