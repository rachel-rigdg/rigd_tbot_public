# tbot_bot/test/test_coa_web_endpoints.py
# Integration/endpoint test for COA Web UI endpoints (/coa, /coa/api, /coa/export), compliant with RIGD TradeBot specifications.
# All web endpoint and CI tests must reside in tbot_bot/test/ per current directory structure.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from flask import Flask
from tbot_web.py.coa_web import coa_web
from pathlib import Path
import sys
from tbot_bot.support.path_resolver import resolve_control_path, get_output_path
from tbot_bot.support.utils_log import log_event

CONTROL_DIR = resolve_control_path()
LOGFILE = get_output_path("logs", "test_mode.log")
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_coa_web_endpoints.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_coa_web_endpoints", msg, logfile=LOGFILE)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_coa_web_endpoints.py] Individual test flag not present. Exiting.")
        sys.exit(1)

class COAWebEndpointTestCase(unittest.TestCase):
    def setUp(self):
        if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
            self.skipTest("Individual test flag not present. Exiting.")
        app = Flask(__name__)
        app.secret_key = "testkey"
        app.register_blueprint(coa_web)
        self.app = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        with self.app.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user'] = 'test_admin'

    def tearDown(self):
        self.ctx.pop()
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    def test_coa_page_loads(self):
        safe_print("[test_coa_web_endpoints] Testing /coa page load...")
        rv = self.app.get('/coa')
        self.assertIn(b'Chart of Accounts (COA) Management', rv.data)
        self.assertEqual(rv.status_code, 200)
        safe_print("[test_coa_web_endpoints] /coa page load OK.")

    def test_coa_api_returns_json(self):
        safe_print("[test_coa_web_endpoints] Testing /coa/api endpoint...")
        rv = self.app.get('/coa/api')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('application/json', rv.content_type)
        data = rv.get_json()
        self.assertIn("metadata", data)
        self.assertIn("accounts", data)
        self.assertIn("history", data)
        safe_print("[test_coa_web_endpoints] /coa/api endpoint OK.")

    def test_export_markdown(self):
        safe_print("[test_coa_web_endpoints] Testing /coa/export/markdown endpoint...")
        rv = self.app.get('/coa/export/markdown')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('text/markdown', rv.content_type)
        safe_print("[test_coa_web_endpoints] /coa/export/markdown endpoint OK.")

    def test_export_csv(self):
        safe_print("[test_coa_web_endpoints] Testing /coa/export/csv endpoint...")
        rv = self.app.get('/coa/export/csv')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('text/csv', rv.content_type)
        safe_print("[test_coa_web_endpoints] /coa/export/csv endpoint OK.")

    def test_coa_rbac_api(self):
        safe_print("[test_coa_web_endpoints] Testing /coa/rbac endpoint...")
        rv = self.app.get('/coa/rbac')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('application/json', rv.content_type)
        data = rv.get_json()
        self.assertTrue(data['user_is_admin'])
        safe_print("[test_coa_web_endpoints] /coa/rbac endpoint OK.")

def run_test():
    result = unittest.main(module=__name__, exit=False)
    status = "PASSED" if result.result.wasSuccessful() else "ERRORS"
    safe_print(f"[test_coa_web_endpoints] FINAL RESULT: {status}.")

if __name__ == "__main__":
    run_test()
