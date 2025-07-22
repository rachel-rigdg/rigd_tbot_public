# tbot_bot/test/test_coa_consistency.py
# Confirms the bot’s COA matches tbot_ledger_coa_template.json and schema; validates correct integration with utils_coa_web.py and coa_utils_ledger.py
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
import json
import os
from pathlib import Path
from tbot_bot.support.utils_coa_web import load_coa_metadata_and_accounts, validate_coa_json
from tbot_bot.accounting.coa_utils_ledger import (
    load_coa_metadata,
    load_coa_accounts,
    validate_coa_structure
)
from tbot_bot.support.path_resolver import resolve_coa_json_path, resolve_coa_metadata_path, resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event

CONTROL_DIR = resolve_control_path()
LOGFILE = get_output_path("logs", "test_mode.log")
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_coa_consistency.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_coa_consistency", msg, logfile=LOGFILE)
    except Exception:
        pass

class TestCOAConsistency(unittest.TestCase):

    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        self.coa_json_path = resolve_coa_json_path()
        self.coa_metadata_path = resolve_coa_metadata_path()
        assert os.path.exists(self.coa_json_path)
        assert os.path.exists(self.coa_metadata_path)

    def tearDown(self):
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    def test_json_structure_and_validation(self):
        safe_print("[test_coa_consistency] Checking JSON structure and validation...")
        coa = load_coa_metadata_and_accounts()
        self.assertIn("metadata", coa)
        self.assertIn("accounts", coa)
        validate_coa_json(coa["accounts"])
        self.assertTrue(isinstance(coa["accounts"], list))
        self.assertGreater(len(coa["accounts"]), 0)
        safe_print("[test_coa_consistency] JSON structure and validation OK.")

    def test_static_vs_loaded_coa(self):
        safe_print("[test_coa_consistency] Comparing static vs loaded COA...")
        with open(self.coa_json_path, "r", encoding="utf-8") as f:
            static_accounts = json.load(f)
        coa = load_coa_metadata_and_accounts()
        self.assertEqual(static_accounts, coa["accounts"])
        safe_print("[test_coa_consistency] Static vs loaded COA match OK.")

    def test_schema_enforcement_via_ledger_utils(self):
        safe_print("[test_coa_consistency] Validating schema via ledger utils...")
        metadata = load_coa_metadata()
        accounts = load_coa_accounts()
        self.assertIsInstance(metadata, dict)
        self.assertIsInstance(accounts, list)
        validate_coa_structure(accounts)
        safe_print("[test_coa_consistency] Schema validation OK.")

    def test_metadata_fields(self):
        safe_print("[test_coa_consistency] Checking metadata fields...")
        coa = load_coa_metadata_and_accounts()
        meta = coa["metadata"]
        for field in ["currency_code", "entity_code", "jurisdiction_code", "coa_version", "created_at_utc", "last_updated_utc"]:
            self.assertIn(field, meta)
        safe_print("[test_coa_consistency] Metadata fields present.")

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_coa_consistency] FINAL RESULT: {status}.")

if __name__ == "__main__":
    run_test()
