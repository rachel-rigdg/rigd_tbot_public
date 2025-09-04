# tbot_bot/test/test_posting_sell_cover.py
import sqlite3
import json
import pytest
from pathlib import Path

# The module under test
from tbot_bot.accounting.ledger_modules import ledger_posting as lp


def _make_min_trades_schema(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Minimal columns actually used by ledger_posting._insert_legs()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datetime_utc TEXT,
            symbol TEXT,
            action TEXT,
            account TEXT,
            total_value REAL,
            group_id TEXT,
            trade_id TEXT,
            strategy TEXT,
            tags TEXT,
            notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _rows_for_trade(db_path: Path, trade_id: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchall()]
    conn.close()
    return rows


def _sum_by_account(rows):
    out = {}
    for r in rows:
        out[r["account"]] = out.get(r["account"], 0.0) + float(r["total_value"] or 0.0)
    return out


def _acct_map(symbol: str):
    acc = lp._coalesce_accounts()
    return {
        "cash": acc["cash"],
        "equity": lp._equity_acct(acc, symbol),
        "short": lp._short_acct(acc, symbol),
        "fees": acc["fees"],
        "pnl": acc["realized_pnl"],
    }


@pytest.fixture
def temp_ledger_db(tmp_path, monkeypatch):
    """Provide a temp ledger db path by monkeypatching resolve_ledger_db_path."""
    db_path = tmp_path / "ledger.db"

    def _fake_resolve(e, j, b, bot_id):
        return str(db_path)

    # Isolate ledger file + silence audit
    monkeypatch.setattr(lp, "resolve_ledger_db_path", _fake_resolve, raising=True)
    monkeypatch.setattr(lp, "audit_append", lambda *a, **k: None, raising=True)

    # Minimal trades schema (lots tables created by ledger_posting via lots_ensure_schema)
    _make_min_trades_schema(db_path)
    return db_path


def test_buy_then_sell_fifo_realized_pnl(temp_ledger_db):
    db_path = temp_ledger_db
    symbol = "XYZ"
    A = _acct_map(symbol)

    # BUY 100 @ 10 + fee 1
    r1 = lp.post_buy(symbol=symbol, qty=100, price=10.0, fee=1.0, trade_id="T-BUY-1", ts_utc="2024-01-01T12:00:00Z")
    assert r1["ok"] and r1["legs"] >= 2

    # SELL 60 @ 12 + fee 1
    r2 = lp.post_sell(symbol=symbol, qty=60, price=12.0, fee=1.0, trade_id="T-SELL-1", ts_utc="2024-01-02T12:00:00Z")
    assert r2["ok"] and r2["legs"] >= 2

    # Inspect only the SELL legs (ignore BUY group)
    sell_rows = _rows_for_trade(db_path, "T-SELL-1")
    assert sell_rows, "no SELL legs recorded"

    sums = _sum_by_account(sell_rows)

    # Expected components
    proceeds = 60 * 12.0                     # 720
    basis = 60 * 10.0                        # 600
    realized = proceeds - basis              # 120
    # Respect fee policy toggle
    expected_realized = realized - (1.0 if lp.FEES_AFFECT_REALIZED_PNL else 0.0)

    # Debits positive; Credits negative
    assert pytest.approx(sums.get(A["cash"], 0.0), rel=0, abs=1e-6) == +proceeds
    assert pytest.approx(sums.get(A["equity"], 0.0), rel=0, abs=1e-6) == -basis

    # Realized P&L: gain => credit (negative); loss => debit (positive)
    pnl_val = sums.get(A["pnl"], 0.0)
    assert pytest.approx(pnl_val, rel=0, abs=1e-6) == (-(expected_realized) if expected_realized > 0 else abs(expected_realized))

    # Fee legs (expense +, cash -)
    assert pytest.approx(sums.get(A["fees"], 0.0), rel=0, abs=1e-6) == +1.0
    # cash already has +proceeds; fee cash is an additional -1.0 (may not be isolated here)
    assert any(r for r in sell_rows if r["account"] == A["cash"] and float(r["total_value"]) == -1.0)


def test_short_open_then_cover_fifo_realized_pnl(temp_ledger_db):
    db_path = temp_ledger_db
    symbol = "ABC"
    A = _acct_map(symbol)

    # SHORT 50 @ 20 (proceeds 1000), fee 0
    r1 = lp.post_short_open(symbol=symbol, qty=50, price=20.0, fee=0.0, trade_id="T-SHORT-OPEN", ts_utc="2024-01-03T12:00:00Z")
    assert r1["ok"] and r1["legs"] >= 2

    # COVER 50 @ 18 (cash out 900), fee 1
    r2 = lp.post_short_cover(symbol=symbol, qty=50, price=18.0, fee=1.0, trade_id="T-SHORT-COVER", ts_utc="2024-01-04T12:00:00Z")
    assert r2["ok"] and r2["legs"] >= 2

    cover_rows = _rows_for_trade(db_path, "T-SHORT-COVER")
    assert cover_rows, "no COVER legs recorded"
    sums = _sum_by_account(cover_rows)

    basis = 50 * 20.0                  # 1000
    cover_cost = 50 * 18.0             # 900
    realized = basis - cover_cost      # 100
    expected_realized = realized - (1.0 if lp.FEES_AFFECT_REALIZED_PNL else 0.0)

    # Remove liability (debit), pay cash (credit)
    assert pytest.approx(sums.get(A["short"], 0.0), rel=0, abs=1e-6) == +basis
    assert pytest.approx(sums.get(A["cash"], 0.0), rel=0, abs=1e-6) == -cover_cost

    # Realized P&L (gain => credit negative)
    pnl_val = sums.get(A["pnl"], 0.0)
    assert pytest.approx(pnl_val, rel=0, abs=1e-6) == (-(expected_realized) if expected_realized > 0 else abs(expected_realized))

    # Fee legs on cover (expense +, cash -)
    assert pytest.approx(sums.get(A["fees"], 0.0), rel=0, abs=1e-6) == +1.0
    assert any(r for r in cover_rows if r["account"] == A["cash"] and float(r["total_value"]) == -1.0)
