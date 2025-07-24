# tbot_bot/test/test_ledger_schema.py
# Tests that new ledgers match COA/schema and double-entry enforcement
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
from tbot_bot.accounting.ledger.ledger_db import validate_ledger_schema
from tbot_bot.support.path_resolver import resolve_control_path
from pathlib import Path
import sys

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_schema.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    result = "PASSED"
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_ledger_schema.py] Individual test flag not present. Exiting.")
        sys.exit(1)
    try:
        import pytest as _pytest
        ret = _pytest.main([__file__])
        if ret != 0:
            result = "ERRORS"
    except Exception as e:
        result = "ERRORS"
        safe_print(f"[test_ledger_schema.py] Exception: {e}")
    finally:
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        safe_print(f"[test_ledger_schema.py] FINAL RESULT: {result}")

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
