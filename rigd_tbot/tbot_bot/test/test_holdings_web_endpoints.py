# tbot_bot/test/test_holdings_web_endpoints.py
# Tests for new Flask blueprint.

import pytest
from flask import Flask
from tbot_web.py.holdings_web import holdings_web

@pytest.fixture
def test_client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(holdings_web, url_prefix="/holdings")
    return app.test_client()

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
