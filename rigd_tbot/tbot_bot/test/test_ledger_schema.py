# tbot_bot/test/test_ledger_schema.py
# Tests that new ledgers match COA/schema and double-entry enforcement
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import pytest
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_coa import validate_ledger_schema
from tbot_bot.support.path_resolver import get_output_path
import json
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
    Validates that ledger data conforms to COA/schema rules and double-entry accounting.
    Does not launch or supervise any persistent process.
    """
    ledger_path = get_output_path("ledger", "ledger_latest.json")
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            ledger_data = json.load(f)
    except Exception as e:
        pytest.fail(f"Failed to load ledger file: {e}")

    valid, errors = validate_ledger_schema(ledger_data)
    assert valid, f"Ledger schema validation failed with errors:\n{errors}"

def run_test():
    import unittest
    try:
        unittest.main(module=__name__, exit=False)
    finally:
        if TEST_FLAG_PATH.exists():
            TEST_FLAG_PATH.unlink()

if __name__ == "__main__":
    try:
        run_test()
    finally:
        if TEST_FLAG_PATH.exists():
            TEST_FLAG_PATH.unlink()
