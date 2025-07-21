# tbot_bot/test/test_ledger_schema.py
# Tests that new ledgers match COA/schema and double-entry enforcement
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
from tbot_bot.accounting.ledger_utils import validate_ledger_schema
from tbot_bot.support.path_resolver import get_output_path
from pathlib import Path
import sys

TEST_FLAG_PATH = get_output_path("control", "test_mode_ledger_schema.flag")
RUN_ALL_FLAG = get_output_path("control", "test_mode.flag")

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_ledger_schema.py] Individual test flag not present. Exiting.")
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
    ret = _pytest.main([__file__])
    if Path(TEST_FLAG_PATH).exists():
        Path(TEST_FLAG_PATH).unlink()
    if ret == 0:
        safe_print("[test_ledger_schema.py] TEST PASSED")
    else:
        safe_print(f"[test_ledger_schema.py] TEST FAILED (code={ret})")

if __name__ == "__main__":
    run_test()
