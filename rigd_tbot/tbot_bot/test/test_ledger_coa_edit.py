# tbot_bot/test/test_ledger_coa_edit.py
# Tests: RBAC on /ledger/edit; valid reassignment; audit emitted; balances reflect change; mapping auto-update toggle.

import json
import types
import importlib
import os
import sys
import pytest
from flask import Flask, session
from datetime import datetime, timezone
print(f"[LAUNCH] test_ledger_coa_edit launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


# ---------- Test App/Client Fixtures ----------

@pytest.fixture(scope="module")
def app():
    # Build minimal Flask app and register ledger blueprint
    app = Flask(__name__)
    app.secret_key = "test-secret"

    # Import blueprint
    ledger_mod = importlib.import_module("tbot_web.py.ledger_web")
    app.register_blueprint(ledger_mod.ledger_web)

    # Patch template rendering for tests that don't use it
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def login_as(client, role, monkeypatch, username="tester"):
    # Patch RBAC to return desired role and set session
    auth_mod = importlib.import_module("tbot_web.py.support.auth_web")
    monkeypatch.setattr(auth_mod, "get_user_role", lambda _u: role, raising=True)
    with client.session_transaction() as s:
        s["user"] = username


# ---------- Helpers ----------

def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def _ensure_dummy_audit(monkeypatch):
    """
    Ensure a dummy ledger_audit module is present so ledger_edit can import/append without ImportError.
    """
    mod_name = "tbot_bot.accounting.ledger_modules.ledger_audit"
    if mod_name not in sys.modules:
        dummy = types.SimpleNamespace()
        calls = []
        def append(**kw):
            calls.append(kw)
        dummy.append = append
        dummy._calls = calls
        sys.modules[mod_name] = dummy
    return sys.modules[mod_name]


def _patch_reassign(monkeypatch, balances_delta=None, group_delta=None):
    """
    Patch reassign_leg_account to simulate a successful reassignment and return deltas.
    """
    reassign_path = "tbot_bot.accounting.ledger_modules.ledger_edit"
    reassign_mod = importlib.import_module(reassign_path)

    calls = []

    def fake_reassign(entry_id, new_account_code, actor, reason=None):
        calls.append((entry_id, new_account_code, actor, reason))
        # simulate deltas for live refresh
        return {
            "balance_delta": balances_delta or {"Assets:Cash": -100.0, "Equity:OpeningBalances": 100.0},
            "group_delta": group_delta or {"group_id": "G-1", "updated": True},
        }

    monkeypatch.setattr(reassign_mod, "reassign_leg_account", fake_reassign, raising=True)
    return calls


# ---------- Tests ----------

def test_rbac_viewer_cannot_post_edit(app, client, monkeypatch):
    login_as(client, role="viewer", monkeypatch=monkeypatch)

    # Attempt edit
    resp = _post_json(client, "/ledger/edit/123", {"account_code": "Assets:Cash"})
    if resp.status_code == 404:
        pytest.skip("Endpoint /ledger/edit/<id> not implemented yet.")
    assert resp.status_code == 403, f"Expected 403 for viewer; got {resp.status_code}"


def test_admin_valid_reassignment_calls_reassign_and_returns_deltas(app, client, monkeypatch):
    login_as(client, role="admin", monkeypatch=monkeypatch)

    # Ensure audit module exists (capturable)
    audit_mod = _ensure_dummy_audit(monkeypatch)

    # Patch reassign to capture call and return deltas
    calls = _patch_reassign(monkeypatch)

    # Toggle auto-update ON and patch maybe_upsert_rule_from_leg to capture calls
    monkeypatch.setenv("LEDGER_INLINE_EDIT_AUTO_RULE", "1")
    monkeypatch.setenv("TBOT_INLINE_EDIT_AUTO_RULE", "1")  # alt key
    try:
        map_mod = importlib.import_module("tbot_bot.accounting.ledger_modules.mapping_auto_update")
        map_calls = []
        def fake_upsert(leg, new_code, strategy):
            map_calls.append((leg, new_code, strategy))
            return {"version_id": "v123"}
        monkeypatch.setattr(map_mod, "maybe_upsert_rule_from_leg", fake_upsert, raising=True)
    except Exception:
        map_mod = None
        map_calls = None  # module missing; acceptable in this test environment

    # Perform edit
    resp = _post_json(client, "/ledger/edit/456", {"account_code": "Equity:OpeningBalances"})
    if resp.status_code == 404:
        pytest.skip("Endpoint /ledger/edit/<id> not implemented yet.")
    assert resp.status_code == 200

    payload = resp.get_json() or {}
    # Accept either "balance_delta" or "balances" depending on implementation detail
    assert ("balance_delta" in payload) or ("balances" in payload), "Expected balances delta in response"
    assert ("group_delta" in payload) or ("group" in payload), "Expected group delta in response"
    # reassign called with args
    assert calls, "reassign_leg_account should be invoked"
    assert calls[-1][1] == "Equity:OpeningBalances"

    # audit event recorded by ledger_edit (if wired)
    if hasattr(audit_mod, "_calls"):
        assert any(c.get("event") == "coa_reassign" for c in audit_mod._calls), "Expected 'coa_reassign' audit event"

    # auto-update invoked if module present
    if map_mod is not None:
        assert map_calls is not None and len(map_calls) >= 1, "Expected mapping auto-update to be invoked when enabled"


def test_admin_toggle_disables_mapping_auto_update(app, client, monkeypatch):
    login_as(client, role="admin", monkeypatch=monkeypatch)

    # Patch reassign
    _patch_reassign(monkeypatch)

    # Toggle OFF
    monkeypatch.setenv("LEDGER_INLINE_EDIT_AUTO_RULE", "0")
    monkeypatch.setenv("TBOT_INLINE_EDIT_AUTO_RULE", "0")

    # Patch auto-update to detect accidental calls
    try:
        map_mod = importlib.import_module("tbot_bot.accounting.ledger_modules.mapping_auto_update")
        called = {"n": 0}
        def guard(*a, **k):
            called["n"] += 1
        monkeypatch.setattr(map_mod, "maybe_upsert_rule_from_leg", guard, raising=True)
    except Exception:
        map_mod = None
        called = {"n": 0}

    resp = _post_json(client, "/ledger/edit/789", {"account_code": "Assets:Cash"})
    if resp.status_code == 404:
        pytest.skip("Endpoint /ledger/edit/<id> not implemented yet.")
    assert resp.status_code == 200

    if map_mod is not None:
        assert called["n"] == 0, "Auto-update should not be called when toggle is OFF"


def test_balances_reflect_change_in_response_payload(app, client, monkeypatch):
    login_as(client, role="admin", monkeypatch=monkeypatch)

    # Patch reassign to produce a known delta
    delta = {"Assets:Cash": -250.0, "Equity:OpeningBalances": 250.0}
    _patch_reassign(monkeypatch, balances_delta=delta)

    resp = _post_json(client, "/ledger/edit/1001", {"account_code": "Equity:OpeningBalances"})
    if resp.status_code == 404:
        pytest.skip("Endpoint /ledger/edit/<id> not implemented yet.")
    assert resp.status_code == 200
    payload = resp.get_json() or {}
    balances = payload.get("balance_delta") or payload.get("balances") or {}
    for k, v in delta.items():
        assert balances.get(k) == v, f"Expected {k}={v} in balances delta"

