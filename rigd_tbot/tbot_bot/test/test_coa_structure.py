# tbot_bot/test/test_coa_structure.py
# NEW: Tests for COA accounts tree CRUD, version history, and RBAC (distinct from mapping tests)

import sys
import json
import types
import pytest
from pathlib import Path
from flask import Flask

# Ensure project root importability
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def fake_utils_module(monkeypatch):
    """
    Provide an in-memory COA store + utils API compatible with tbot_web.support.utils_coa_web
    so we can test CRUD and versioning without touching the filesystem.
    """
    mod = types.ModuleType("tbot_web.support.utils_coa_web")

    # In-memory state
    state = {
        "version": 1,
        "metadata": {
            "currency_code": "USD",
            "entity_code": "ENT",
            "jurisdiction_code": "US",
            "created_at_utc": "2025-01-01T00:00:00+00:00",
            "last_updated_utc": "2025-01-01T00:00:00+00:00",
        },
        "accounts": [
            {"code": "Assets", "name": "Assets", "children": [
                {"code": "Assets:Cash", "name": "Cash"}
            ]},
            {"code": "Equity", "name": "Equity"}
        ],
        "history": []
    }

    def _flatten(accs):
        flat = []
        def walk(a):
            flat.append({"code": a["code"], "name": a.get("name", "")})
            for c in a.get("children", []) or []:
                walk(c)
        for a in accs:
            walk(a)
        return flat

    def load_coa_metadata_and_accounts():
        return {
            "metadata": dict(state["metadata"]),
            "accounts": json.loads(json.dumps(state["accounts"])),
            "accounts_flat": _flatten(state["accounts"]),
            "history": list(state["history"]),
        }

    def validate_coa_json(accounts):
        # Minimal validation: codes unique and not empty
        flat_codes = []
        def walk(a):
            code = a.get("code", "").strip()
            if not code:
                raise ValueError("Empty account code")
            flat_codes.append(code)
            for c in a.get("children", []) or []:
                walk(c)
        for a in accounts:
            walk(a)
        if len(set(flat_codes)) != len(flat_codes):
            raise ValueError("Duplicate account code detected")
        return True

    def compute_coa_diff(old, new):
        old_codes = {j["code"] for j in _flatten(old)}
        new_codes = {j["code"] for j in _flatten(new)}
        return {
            "added": sorted(list(new_codes - old_codes)),
            "removed": sorted(list(old_codes - new_codes)),
            "unchanged": sorted(list(old_codes & new_codes)),
        }

    def save_coa_json(accounts, *, user="test", diff=None):
        validate_coa_json(accounts)
        state["accounts"] = json.loads(json.dumps(accounts))
        state["version"] += 1
        state["metadata"]["last_updated_utc"] = "2025-01-02T00:00:00+00:00"
        state["history"].append({
            "timestamp_utc": state["metadata"]["last_updated_utc"],
            "user": user,
            "summary": f"COA updated to v{state['version']}",
            "diff": json.dumps(diff or compute_coa_diff([], accounts)),
            "version": state["version"],
        })
        return True

    def export_coa_markdown(coa):
        return "# COA\n" + "\n".join(f"* {a['code']}" for a in _flatten(coa.get("accounts", [])))

    def export_coa_csv(coa):
        return "code,name\n" + "\n".join(f"{a['code']},{a['name']}" for a in _flatten(coa.get("accounts", [])))

    def get_coa_audit_log(limit=50):
        return list(state["history"])[-limit:]

    # Bind functions to module
    mod.load_coa_metadata_and_accounts = load_coa_metadata_and_accounts
    mod.save_coa_json = save_coa_json
    mod.export_coa_markdown = export_coa_markdown
    mod.export_coa_csv = export_coa_csv
    mod.get_coa_audit_log = get_coa_audit_log
    mod.compute_coa_diff = compute_coa_diff
    mod.validate_coa_json = validate_coa_json

    monkeypatch.setitem(sys.modules, "tbot_web.support.utils_coa_web", mod)
    return mod


@pytest.fixture
def fake_auth_module(monkeypatch):
    """
    Provide a minimal RBAC decorator compatible with tbot_web.support.auth_web.rbac_required
    that checks Flask session['role'] when role="admin".
    """
    mod = types.ModuleType("tbot_web.support.auth_web")

    def rbac_required(role=None):
        def deco(fn):
            from functools import wraps
            @wraps(fn)
            def wrapped(*args, **kwargs):
                from flask import session
                if role == "admin" and session.get("role") != "admin":
                    return ("Forbidden", 403)
                return fn(*args, **kwargs)
            return wrapped
        return deco

    mod.rbac_required = rbac_required
    monkeypatch.setitem(sys.modules, "tbot_web.support.auth_web", mod)
    return mod


@pytest.fixture
def coa_app_client(monkeypatch, fake_utils_module, fake_auth_module):
    """
    Flask test client with the COA blueprint registered and identity guard disabled.
    """
    # Import after fakes are installed
    from tbot_web.py import coa_web as coa_bp_module

    # Bypass identity checks for tests
    monkeypatch.setattr(coa_bp_module, "identity_guard", lambda: False, raising=False)

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(coa_bp_module.coa_web)

    return app.test_client()


def test_coa_api_lists_accounts_and_metadata(coa_app_client):
    resp = coa_app_client.get("/coa/api")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "metadata" in data and "accounts" in data and "history" in data
    assert isinstance(data["accounts"], list)
    # Ensure at least the base "Assets" account is present from fake utils
    codes = {a["code"] for a in data["accounts"]}
    assert "Assets" in codes


def test_coa_read_page_renders_html(coa_app_client):
    # Any role can view; no RBAC restriction on GET /coa beyond identity guard
    with coa_app_client.session_transaction() as sess:
        sess["role"] = "user"
    resp = coa_app_client.get("/coa")
    assert resp.status_code == 200
    assert b"COA Metadata" in resp.data


def test_coa_edit_requires_admin(coa_app_client):
    # Non-admin should be forbidden
    with coa_app_client.session_transaction() as sess:
        sess["role"] = "user"
    resp = coa_app_client.post("/coa/edit", data={"coa_json": "[]"})
    assert resp.status_code == 403


def test_coa_tree_crud_and_version_history(coa_app_client, fake_utils_module):
    # Admin performs an edit: add a new child account under Assets
    with coa_app_client.session_transaction() as sess:
        sess["role"] = "admin"
        sess["user"] = "admin_tester"

    # Fetch current tree
    data = coa_app_client.get("/coa/api").get_json()
    accounts = data["accounts"]

    # Add child node under Assets
    for a in accounts:
        if a["code"] == "Assets":
            a.setdefault("children", []).append({"code": "Assets:Securities", "name": "Securities"})
            break

    # Save via POST /coa/edit
    resp = coa_app_client.post("/coa/edit", data={"coa_json": json.dumps(accounts)}, follow_redirects=False)
    assert resp.status_code in (302, 303), f"Expected redirect after save, got {resp.status_code}"

    # Verify new version in API + audit history increased
    data2 = coa_app_client.get("/coa/api").get_json()
    codes = {n["code"] for n in data2["accounts"]}
    assert "Assets:Securities" in codes

    history = data2.get("history", [])
    assert isinstance(history, list) and len(history) >= 1
    assert any("COA updated" in (h.get("summary") or "") for h in history)

    # Second edit: delete Equity account → version should advance again
    accounts2 = data2["accounts"]
    accounts2 = [a for a in accounts2 if a["code"] != "Equity"]
    resp2 = coa_app_client.post("/coa/edit", data={"coa_json": json.dumps(accounts2)}, follow_redirects=False)
    assert resp2.status_code in (302, 303)

    data3 = coa_app_client.get("/coa/api").get_json()
    codes3 = {n["code"] for n in data3["accounts"]}
    assert "Equity" not in codes3
    # History grew
    assert len(data3.get("history", [])) >= len(history) + 1


def test_coa_export_endpoints_return_content(coa_app_client):
    # Markdown
    md = coa_app_client.get("/coa/export/markdown")
    assert md.status_code == 200
    assert md.mimetype in ("text/markdown", "text/plain", "application/octet-stream")
    assert md.data  # not empty
    # CSV
    csv = coa_app_client.get("/coa/export/csv")
    assert csv.status_code == 200
    assert csv.mimetype in ("text/csv", "text/plain", "application/octet-stream")
    assert csv.data  # not empty
