# tbot_bot/test/test_coa_consistency.py
# Confirms the bot’s COA matches tbot_ledger_coa_template.json and schema; validates correct integration with utils_coa_web.py and coa_utils_ledger.py
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# All process orchestration is via tbot_supervisor.py only.

import unittest
import json
import os

from tbot_bot.support.utils_coa_web import load_coa_metadata_and_accounts, validate_coa_json
from tbot_bot.accounting.coa_utils_ledger import (
    load_coa_metadata,
    load_coa_accounts,
    validate_coa_structure
)

# Path to static COA reference file
from tbot_bot.support.path_resolver import resolve_coa_json_path, resolve_coa_metadata_path

class TestCOAConsistency(unittest.TestCase):

    def setUp(self):
        self.coa_json_path = resolve_coa_json_path()
        self.coa_metadata_path = resolve_coa_metadata_path()
        assert os.path.exists(self.coa_json_path)
        assert os.path.exists(self.coa_metadata_path)

    def test_json_structure_and_validation(self):
        # Load via utils_coa_web.py
        coa = load_coa_metadata_and_accounts()
        self.assertIn("metadata", coa)
        self.assertIn("accounts", coa)
        validate_coa_json(coa["accounts"])
        self.assertTrue(isinstance(coa["accounts"], list))
        self.assertGreater(len(coa["accounts"]), 0)

    def test_static_vs_loaded_coa(self):
        # Compare static JSON reference to runtime loaded
        with open(self.coa_json_path, "r", encoding="utf-8") as f:
            static_accounts = json.load(f)
        coa = load_coa_metadata_and_accounts()
        self.assertEqual(static_accounts, coa["accounts"])

    def test_schema_enforcement_via_ledger_utils(self):
        # Validate with coa_utils_ledger.py
        metadata = load_coa_metadata()
        accounts = load_coa_accounts()
        self.assertIsInstance(metadata, dict)
        self.assertIsInstance(accounts, list)
        validate_coa_structure(accounts)

    def test_metadata_fields(self):
        coa = load_coa_metadata_and_accounts()
        meta = coa["metadata"]
        for field in ["currency_code", "entity_code", "jurisdiction_code", "coa_version", "created_at_utc", "last_updated_utc"]:
            self.assertIn(field, meta)

if __name__ == "__main__":
    print("[test_coa_consistency.py] Direct execution is not permitted. This test must only be run via the test harness.")
    import sys
    sys.exit(1)
