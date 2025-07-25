# tbot_bot/test/test_ledger_schema.py
# Tests that new ledgers match COA/schema and double-entry enforcement
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
import time
from tbot_bot.accounting.ledger_modules.ledger_db import validate_ledger_schema
from tbot_bot.support.path_resolver import resolve_control_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_ledger_schema.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_ledger_schema", msg)
    except Exception:
        pass

if __name__ == "__main__":
    result = "PASSED"
    start_time = time.time()
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
        elapsed = time.time() - start_time
        if elapsed > MAX_TEST_TIME:
            safe_print(f"[test_ledger_schema.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
            result = "ERRORS"
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
