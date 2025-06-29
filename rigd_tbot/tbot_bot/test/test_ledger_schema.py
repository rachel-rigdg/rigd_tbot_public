# tbot_bot/test/test_ledger_schema.py
# Tests that new ledgers match COA/schema and double-entry enforcement
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# All process orchestration is via tbot_supervisor.py only.

import pytest
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_coa import validate_ledger_schema
from tbot_bot.support.path_resolver import get_output_path
import json

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
