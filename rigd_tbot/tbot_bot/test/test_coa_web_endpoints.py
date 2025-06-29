# tbot_bot/test/test_coa_web_endpoints.py
# Integration/endpoint test for COA Web UI endpoints (/coa, /coa/api, /coa/export), compliant with RIGD TradeBot specifications.
# All web endpoint and CI tests must reside in tbot_bot/test/ per current directory structure.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import unittest
from flask import Flask
from tbot_web.py.coa_web import coa_web
from pathlib import Path
import sys

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_coa_web_endpoints.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        print("[test_coa_web_endpoints.py] Individual test flag not present. Exiting.")
        sys.exit(1)

class COAWebEndpointTestCase(unittest.TestCase):
    def setUp(self):
        if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
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
        if TEST_FLAG_PATH.exists():
            TEST_FLAG_PATH.unlink()

    def test_coa_page_loads(self):
        rv = self.app.get('/coa')
        self.assertIn(b'Chart of Accounts (COA) Management', rv.data)
        self.assertEqual(rv.status_code, 200)

    def test_coa_api_returns_json(self):
        rv = self.app.get('/coa/api')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('application/json', rv.content_type)
        data = rv.get_json()
        self.assertIn("metadata", data)
        self.assertIn("accounts", data)
        self.assertIn("history", data)

    def test_export_markdown(self):
        rv = self.app.get('/coa/export/markdown')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('text/markdown', rv.content_type)

    def test_export_csv(self):
        rv = self.app.get('/coa/export/csv')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('text/csv', rv.content_type)

    def test_coa_rbac_api(self):
        rv = self.app.get('/coa/rbac')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('application/json', rv.content_type)
        data = rv.get_json()
        self.assertTrue(data['user_is_admin'])

def run_test():
    unittest.main(module=__name__, exit=False)

if __name__ == "__main__":
    run_test()
