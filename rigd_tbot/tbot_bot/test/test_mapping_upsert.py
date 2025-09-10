# tests/accounting/test_mapping_upsert.py
# Tests: upsert_rule creates version; rollback restores prior; inline-edit path produces expected rule key & version.

import json
import importlib
from pathlib import Path

import pytest
from datetime import datetime, timezone
print(f"[LAUNCH] test_mapping_upsert launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)



@pytest.fixture()
def tmp_mapping_env(tmp_path, monkeypatch):
    """
    Isolate mapping table to a temp file and patch resolvers/identity so tests don't touch real data.
    """
    mapping_path = tmp_path / "coa_mapping_table.json"

    # Patch path resolver inside the target module
    cm = importlib.import_module("tbot_bot.accounting.coa_mapping_table")
    monkeypatch.setattr(
        cm,
        "resolve_coa_mapping_json_path",
        lambda e, j, b, bid: mapping_path,
        raising=True,
    )
    # Stable identity for tests
    monkeypatch.setattr(
        cm,
        "get_bot_identity",
        lambda: "ENT_US_TEST_BOT1",
        raising=True,
    )
    # Re-import to ensure patched symbols are used downstream
    importlib.reload(cm)

    return {"module": cm, "mapping_path": mapping_path}


def read_table(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def version_num(table) -> int:
    return int(table.get("version", 0) or 0)


def list_rule_keys(table):
    return [m.get("rule_key") for m in table.get("mappings", []) if isinstance(m, dict)]


def get_versions_dir(mapping_path: Path) -> Path:
    return mapping_path.parent / "coa_mapping_versions"


def test_upsert_rule_creates_version_and_persists(tmp_mapping_env):
    cm = tmp_mapping_env["module"]
    mapping_path = tmp_mapping_env["mapping_path"]

    # Load (creates file) and record base version
    t0 = cm.load_mapping_table()
    v0 = version_num(t0)

    # Upsert a new rule
    rule_key = "TRNTYPE=BUY|symbol=AAPL|memo=filled|broker=TEST"
    ctx_meta = {"TRNTYPE": "BUY", "symbol": "AAPL", "memo": "filled", "broker": "TEST"}
    vinfo = cm.upsert_rule(rule_key, "Assets:Cash", ctx_meta, actor="tester")

    assert vinfo and "version_id" in vinfo
    t1 = read_table(mapping_path)
    assert t1 is not None
    assert version_num(t1) > v0
    assert rule_key in list_rule_keys(t1)
    # Validate persisted mapping fields
    stored = [m for m in t1["mappings"] if m.get("rule_key") == rule_key][0]
    assert stored.get("account_code") == "Assets:Cash"
    assert stored.get("context") == ctx_meta
    assert stored.get("updated_by") == "tester"


def test_rollback_restores_prior_version(tmp_mapping_env):
    cm = tmp_mapping_env["module"]
    mapping_path = tmp_mapping_env["mapping_path"]

    # Seed with first rule
    rk1 = "TRNTYPE=BUY|symbol=AAPL|memo=filled|broker=TEST"
    cm.upsert_rule(rk1, "Assets:Cash", {"TRNTYPE": "BUY", "symbol": "AAPL"}, actor="seed")
    t1 = read_table(mapping_path)
    v1 = version_num(t1)

    # Add a second rule
    rk2 = "TRNTYPE=DIV|symbol=AAPL|memo=dividend|broker=TEST"
    cm.upsert_rule(rk2, "Income:Dividends", {"TRNTYPE": "DIV", "symbol": "AAPL"}, actor="seed2")
    t2 = read_table(mapping_path)
    v2 = version_num(t2)
    assert v2 > v1 and rk2 in list_rule_keys(t2)

    # Rollback to version v1
    assert cm.rollback_mapping_version(v1) is True

    # After rollback, table content should match snapshot of v1 (though version will bump again on save)
    t_after = read_table(mapping_path)
    keys_after = set(list_rule_keys(t_after))
    assert rk1 in keys_after
    assert rk2 not in keys_after


def test_inline_edit_maybe_upsert_rule_from_leg(tmp_mapping_env, monkeypatch):
    # Ensure mapping_auto_update uses the patched coa_mapping_table
    cm = tmp_mapping_env["module"]
    mau = importlib.import_module("tbot_bot.accounting.ledger_modules.mapping_auto_update")
    importlib.reload(mau)

    # Patch identity in mapping_auto_update as well (if referenced)
    monkeypatch.setenv("TBOT_INLINE_EDIT_AUTO_RULE", "1")  # ensure feature-on semantics if consulted

    # Base version
    mapping_path = tmp_mapping_env["mapping_path"]
    base = read_table(mapping_path) or cm.load_mapping_table()
    v0 = version_num(base)

    # Simulated leg context from ledger (BUY AAPL)
    leg = {
        "TRNTYPE": "BUY",
        "symbol": "AAPL",
        "memo": "Filled @ 150",
        "broker_code": "TEST",
        "group_id": "G123",
        "id": 42,
    }
    res = mau.maybe_upsert_rule_from_leg(leg, "Assets:Cash", strategy="open")
    assert isinstance(res, dict) and "version_id" in res

    # Verify a new version and presence of a rule containing tokens from context
    t_after = read_table(mapping_path)
    v1 = version_num(t_after)
    assert v1 > v0

    rules_text = json.dumps(t_after.get("mappings", []))
    # Heuristic: ensure key context fragments are present
    assert "BUY" in rules_text.upper()
    assert "AAPL" in rules_text.upper()
    assert "ASSETS:Cash".upper() in rules_text.upper()
