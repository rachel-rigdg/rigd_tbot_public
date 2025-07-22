# tbot_bot/test/test_holdings_web_endpoints.py
# Tests for new Flask blueprint.

import pytest
from flask import Flask
from tbot_web.py.holdings_web import holdings_web
from tbot_bot.support.path_resolver import resolve_control_path
from pathlib import Path
import sys

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_holdings_web_endpoints.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

@pytest.fixture
def test_client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(holdings_web, url_prefix="/holdings")
    return app.test_client()

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_holdings_web_endpoints.py] Individual test flag not present. Exiting.")
        sys.exit(0)

def test_get_holdings_config(test_client):
    resp = test_client.get("/holdings/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "HOLDINGS_ETF_LIST" in data
    assert isinstance(data["HOLDINGS_ETF_LIST"], str)

def test_post_holdings_config_valid(test_client):
    payload = {
        "HOLDINGS_FLOAT_TARGET_PCT": 10,
        "HOLDINGS_TAX_RESERVE_PCT": 20,
        "HOLDINGS_PAYROLL_PCT": 10,
        "HOLDINGS_REBALANCE_INTERVAL": 6,
        "HOLDINGS_ETF_LIST": "SCHD:50,SCHY:50"
    }
    resp = test_client.post("/holdings/config", json=payload)
    assert resp.status_code == 200

def test_get_holdings_status(test_client):
    resp = test_client.get("/holdings/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "account_value" in data
    assert "cash" in data
    assert "etf_holdings" in data
    assert "next_rebalance_due" in data
