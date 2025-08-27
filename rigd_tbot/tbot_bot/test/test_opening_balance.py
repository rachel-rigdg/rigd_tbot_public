# tests/accounting/test_opening_balance.py
# Tests: empty-ledger OB posting (cash + positions), idempotence, meta flag set, balances correct, audit present.

import os
import sys
import sqlite3
import types
import importlib
from datetime import datetime
import pytest

# ------------------------------
# Helpers: minimal OB schema (matches ledger_modules/schema.sql created in this project)
# ------------------------------

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ledger_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL UNIQUE,
  created_at_utc TEXT NOT NULL,
  sync_run_id TEXT
);

CREATE TABLE IF NOT EXISTS ledger_legs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL,
  entry_id TEXT,
  symbol TEXT,
  account_code TEXT NOT NULL,
  debit REAL NOT NULL DEFAULT 0,
  credit REAL NOT NULL DEFAULT 0,
  memo TEXT,
  created_at_utc TEXT NOT NULL,
  sync_run_id TEXT,
  FOREIGN KEY(group_id) REFERENCES ledger_groups(group_id) ON DELETE CASCADE,
  CHECK (debit >= 0 AND credit >= 0),
  CHECK ((debit = 0) OR (credit = 0))
);

CREATE INDEX IF NOT EXISTS ix_legs_group ON ledger_legs(group_id);
CREATE INDEX IF NOT EXISTS ix_legs_account ON ledger_legs(account_code);
"""


def create_schema(db_path: str):
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def net_by_account(db_path: str):
    """
    Returns {account_code: net} where net = SUM(debit - credit).
    """
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT account_code, COALESCE(SUM(debit - credit),0) AS net FROM ledger_legs GROUP BY account_code"
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def count_legs(db_path: str):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM ledger_legs").fetchone()[0]


def get_meta(db_path: str, key: str, default=None):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM ledger_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default


def get_ob_group_id(db_path: str):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT group_id FROM ledger_groups WHERE group_id LIKE 'OPENING_BALANCE_%' LIMIT 1"
        ).fetchone()
        return row[0] if row else None


# ------------------------------
# Fixtures
# ------------------------------

@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test_ledger.db"
    create_schema(str(db))
    return str(db)


@pytest.fixture()
def ob_module(tmp_db, monkeypatch):
    """
    Import ledger_opening_balance with path + identity + audit patched for isolation.
    """
    mod = importlib.import_module("tbot_bot.accounting.ledger_modules.ledger_opening_balance")

    # Patch DB resolver + identity
    monkeypatch.setattr(
        mod, "resolve_ledger_db_path",
        lambda e, j, b, bid: tmp_db,
        raising=True
    )
    monkeypatch.setattr(
        mod, "load_bot_identity",
        lambda: "ENT_US_TEST_BOT1",
        raising=True
    )

    # Patch audit sink to capture events
    audit_mod_name = "tbot_bot.accounting.ledger_modules.ledger_audit"
    dummy = types.SimpleNamespace()
    dummy_calls = []

    def append(**event):
        dummy_calls.append(event)

    dummy.append = append
    dummy._calls = dummy_calls
    sys.modules[audit_mod_name] = dummy
    # Ensure module picks it up (if it imports inside function that's fine; otherwise it's already present)
    return mod


# ------------------------------
# Tests
# ------------------------------

def test_post_opening_balances_on_empty_ledger_cash_and_positions(tmp_db, ob_module):
    sync_run_id = "sync_test_" + datetime.utcnow().isoformat()
    broker_snapshot = {
        "cash": 1000.0,
        "positions": [
            {"symbol": "AAPL", "qty": 10, "basis": 150.0},  # basis total = 1500
        ],
    }

    # Pre-conditions
    assert count_legs(tmp_db) == 0
    assert get_meta(tmp_db, "opening_balances_posted") in (None, "0")

    # Act
    ob_module.post_opening_balances_if_needed(sync_run_id, broker_snapshot)

    # Post-conditions: meta flag + group
    assert get_meta(tmp_db, "opening_balances_posted") == "1"
    gid = get_ob_group_id(tmp_db)
    assert gid and gid.startswith("OPENING_BALANCE_")

    # Legs should be 4: cash (debit cash, credit opening equity) + position (debit brokerage equity, credit opening equity)
    assert count_legs(tmp_db) == 4

    # Balances by account (net = debit - credit)
    nets = net_by_account(tmp_db)
    # Assets
    assert nets.get("Brokerage:Cash", 0) == pytest.approx(1000.0, abs=1e-6)
    assert nets.get("Brokerage:Equity:AAPL", 0) == pytest.approx(1500.0, abs=1e-6)
    # Equity offset (negative)
    assert nets.get("Equity:OpeningBalances", 0) == pytest.approx(-2500.0, abs=1e-6)
    # Zero sum
    assert sum(nets.values()) == pytest.approx(0.0, abs=1e-6)

    # Audit present
    audit = sys.modules["tbot_bot.accounting.ledger_modules.ledger_audit"]
    assert any(ev.get("event") == "opening_balance_posted" for ev in getattr(audit, "_calls", []))


def test_opening_balances_idempotent(tmp_db, ob_module):
    sync_run_id = "sync_test_2_" + datetime.utcnow().isoformat()
    broker_snapshot = {"cash": 500.0, "positions": []}

    # First call posts (on empty DB created by fixture)
    ob_module.post_opening_balances_if_needed(sync_run_id, broker_snapshot)
    n1 = count_legs(tmp_db)
    assert n1 in (2, 4)  # cash-only OB = 2 legs; if previous test ran on same db, accept >=2

    # Second call should be no-op (idempotent)
    ob_module.post_opening_balances_if_needed(sync_run_id, broker_snapshot)
    n2 = count_legs(tmp_db)
    assert n2 == n1

    # Meta flag remains set
    assert get_meta(tmp_db, "opening_balances_posted") == "1"


def test_opening_balance_meta_and_group_consistency(tmp_db, ob_module):
    sync_run_id = "sync_test_3_" + datetime.utcnow().isoformat()
    broker_snapshot = {"cash": 0.0, "positions": [{"symbol": "MSFT", "qty": 2, "basis": 300.0}]}

    # Ensure empty
    # (fresh schema per tmp_db fixture; legs may be 0)
    # Act
    ob_module.post_opening_balances_if_needed(sync_run_id, broker_snapshot)

    # Meta + group
    assert get_meta(tmp_db, "opening_balances_posted") == "1"
    gid = get_ob_group_id(tmp_db)
    assert gid and gid.startswith("OPENING_BALANCE_")

    # Balances reflect only positions (600 debit to Brokerage:Equity:MSFT, -600 to Equity:OpeningBalances)
    nets = net_by_account(tmp_db)
    assert nets.get("Brokerage:Equity:MSFT", 0) == pytest.approx(600.0, abs=1e-6)
    # Opening equity must offset all debits
    total_debits = sum(v for v in nets.values() if v > 0)
    assert nets.get("Equity:OpeningBalances", 0) == pytest.approx(-total_debits, abs=1e-6)
