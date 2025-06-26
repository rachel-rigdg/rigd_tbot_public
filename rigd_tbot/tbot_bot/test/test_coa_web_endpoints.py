# tbot_bot/test/test_coa_web_endpoints.py
# Integration/endpoint test for COA Web UI endpoints (/coa, /coa/api, /coa/export), compliant with RIGD TradeBot specifications.
# All web endpoint and CI tests must reside in tbot_bot/test/ per current directory structure.
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# All process orchestration is via tbot_supervisor.py only.

import unittest
from flask import Flask
from tbot_web.py.coa_web import coa_web

class COAWebEndpointTestCase(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "testkey"
        app.register_blueprint(coa_web)
        self.app = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        # Mock session as admin for edit tests
        with self.app.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user'] = 'test_admin'

    def tearDown(self):
        self.ctx.pop()

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

if __name__ == "__main__":
    print("[test_coa_web_endpoints.py] Direct execution is not permitted. This test must only be run via the test harness.")
    import sys
    sys.exit(1)
