# tbot_bot/test/test_ledger_web.py
# Tests for the Ledger Web blueprint:
# - /ledger/reconcile (HTML list page with balances)
# - /ledger/group/<group_id> (JSON)
# - /ledger/search (JSON)
# - /ledger/collapse_expand/<group_id> (JSON)
# - RBAC / identity guard behavior
#
# These tests DO NOT touch real DBs or files — all dependencies are monkeypatched.

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def app(monkeypatch):
    # Import the blueprint module
    from tbot_web.py import ledger_web as lw

    # ---- Monkeypatch guards to allow access by default
    monkeypatch.setattr(lw, "provisioning_guard", lambda: False)
    monkeypatch.setattr(lw, "identity_guard", lambda: False)

    # ---- Monkeypatch grouped-trades & group-by-id
    fake_group_id = "group-abc-123"
    fake_groups_collapsed = [
        {
            "group_id": fake_group_id,
            "collapsed": True,
            "symbol": "AAPL",
            "timestamp_utc": "2025-02-10T15:04:05+00:00",
            "account": "Assets:Cash",
            "trntype": "long",
            "action": "long",
            "quantity": 5,
            "price": 100,
            "fee": 0.5,
            "total_value": 500.5,
            "status": "ok",
            "sub_entries": [
                {
                    "id": 1,
                    "group_id": fake_group_id,
                    "trade_id": "T1",
                    "timestamp_utc": "2025-02-10T15:04:05+00:00",
                    "symbol": "AAPL",
                    "account": "Assets:Investments:AAPL",
                    "side": "debit",
                    "quantity": 5,
                    "price": 100,
                    "total_value": 500.0,
                    "fee": 0.5,
                    "strategy": "open",
                },
                {
                    "id": 2,
                    "group_id": fake_group_id,
                    "trade_id": "T1",
                    "timestamp_utc": "2025-02-10T15:04:05+00:00",
                    "symbol": "AAPL",
                    "account": "Assets:Cash",
                    "side": "credit",
                    "quantity": 0,
                    "price": None,
                    "total_value": -500.5,
                    "fee": 0.0,
                    "strategy": "open",
                },
            ],
        }
    ]
    monkeypatch.setattr(lw, "fetch_grouped_trades", lambda *a, **k: fake_groups_collapsed)
    monkeypatch.setattr(lw, "fetch_trade_group_by_id", lambda gid: fake_groups_collapsed[0]["sub_entries"])

    # ---- Monkeypatch balances provider used inside the view
    # It is imported at call-time as:
    #   from tbot_bot.accounting.ledger_modules.ledger_balance import calculate_account_balances
    from tbot_bot.accounting.ledger_modules import ledger_balance as lb
    monkeypatch.setattr(
        lb,
        "calculate_account_balances",
        lambda **kw: {
            "Assets:Cash": {
                "opening_balance": 1000,
                "debits": 500.5,
                "credits": 0,
                "closing_balance": 1500.5,
            },
            "Assets:Investments:AAPL": {
                "opening_balance": 0,
                "debits": 0,
                "credits": 0,
                "closing_balance": 500.0,  # illustrative only
            },
        },
    )

    # ---- Monkeypatch COA accounts list for the select menus
    monkeypatch.setattr(
        lw,
        "load_coa_metadata_and_accounts",
        lambda: {"accounts_flat": [("Assets:Cash", "Cash"), ("Assets:Investments:AAPL", "AAPL Position")]},
    )

    # ---- Monkeypatch search
    monkeypatch.setattr(
        lw,
        "search_trades",
        lambda search_term=None, sort_by="datetime_utc", sort_desc=True, limit=1000, offset=0: [
            {
                "group_id": fake_group_id,
                "symbol": "AAPL",
                "timestamp_utc": "2025-02-10T15:04:05+00:00",
                "account": "Assets:Cash",
                "action": "long",
                "quantity": 5,
                "price": 100,
                "fee": 0.5,
                "total_value": 500.5,
                "status": "ok",
                "collapsed": True,
                "sub_entries": [],
            }
        ],
    )

    # ---- Monkeypatch collapse toggle handler
    monkeypatch.setattr(lw, "collapse_expand_group", lambda *a, **k: True)

    # Build a tiny Flask app and register the blueprint
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test", TESTING=True)
    app.register_blueprint(lw.ledger_web, url_prefix="")  # keep route paths as defined in the module
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_list_page_renders_and_contains_balances(client):
    resp = client.get("/ledger/reconcile")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Table headings we expect
    assert "Reconciliation Table" in html
    assert "Account Balances" in html
    # A couple of values from the monkeypatched data
    assert "Assets:Cash" in html
    assert "AAPL" in html


def test_group_detail_json_shape(client):
    resp = client.get("/ledger/group/group-abc-123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    row = data[0]
    # minimal shape checks
    assert "group_id" in row
    assert "trade_id" in row
    assert "account" in row
    assert "timestamp_utc" in row or "datetime_utc" in row


def test_search_endpoint_json_shape(client):
    resp = client.get("/ledger/search?q=AAPL&sort_desc=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert data, "Expected at least one result"
    first = data[0]
    for key in ("symbol", "account", "total_value", "collapsed"):
        assert key in first


def test_collapse_expand_endpoint(client):
    resp = client.post("/ledger/collapse_expand/group-abc-123", json={"collapsed_state": 1})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True
    assert "result" in data


def test_rbac_identity_guard_blocks_json(monkeypatch, app, client):
    # Force identity guard to deny access
    from tbot_web.py import ledger_web as lw
    monkeypatch.setattr(lw, "identity_guard", lambda: True)
    resp = client.get("/ledger/search?q=foo")
    assert resp.status_code == 403
    data = resp.get_json()
    assert "error" in data
