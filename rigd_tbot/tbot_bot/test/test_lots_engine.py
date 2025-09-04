# tbot_bot/test/test_lots_engine.py
import sqlite3
import math

import pytest

from tbot_bot.accounting.lots_engine import (
    ensure_schema,
    record_open,
    allocate_for_close,
    record_close,
)

TOL = 1e-9


def _fetch_lots(conn):
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, symbol, side, qty_open, qty_remaining, unit_cost, fees_alloc, opened_trade_id, opened_at "
        "FROM lots ORDER BY id ASC"
    ).fetchall()
    return [dict(zip([c[0] for c in cur.description], r)) for r in rows]


def test_long_fifo_close_two_lots():
    """
    Open two long lots, close across both FIFO, and validate:
      - qty_remaining is reduced correctly per lot
      - basis_total, proceeds_total, realized_pnl_total in summary are correct
    """
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)

    # Open two long lots: 10 @ 100, then 10 @ 120
    lot1_id = record_open(conn, symbol="AAPL", qty=10, unit_cost=100.0, side="long", fees=0.0, opened_trade_id="T1")
    lot2_id = record_open(conn, symbol="AAPL", qty=10, unit_cost=120.0, side="long", fees=0.0, opened_trade_id="T2")

    lots_before = _fetch_lots(conn)
    assert len(lots_before) == 2
    assert lots_before[0]["qty_remaining"] == 10
    assert lots_before[1]["qty_remaining"] == 10

    # Allocate FIFO to close 15 shares
    allocs = allocate_for_close(conn, symbol="AAPL", qty_to_close=15, side="long", policy="FIFO")
    # Expect: 10 from lot1, 5 from lot2
    assert len(allocs) == 2
    assert allocs[0]["lot_id"] == lot1_id and math.isclose(allocs[0]["qty"], 10.0, rel_tol=0, abs_tol=TOL)
    assert allocs[1]["lot_id"] == lot2_id and math.isclose(allocs[1]["qty"], 5.0, rel_tol=0, abs_tol=TOL)

    # Sell 15 @ 130 → proceeds = 1950; basis = 10*100 + 5*120 = 1600; realized = 350 (fees ignored for PnL)
    proceeds = 15 * 130.0
    summary = record_close(
        conn,
        allocations=allocs,
        close_trade_id="T3",
        proceeds_total=proceeds,
        total_close_fees=0.0,
        pnl_fees_affect=False,
    )
    assert math.isclose(summary["qty_closed"], 15.0, rel_tol=0, abs_tol=TOL)
    assert math.isclose(summary["basis_total"], 1600.0, rel_tol=0, abs_tol=TOL)
    assert math.isclose(summary["proceeds_total"], 1950.0, rel_tol=0, abs_tol=TOL)
    assert math.isclose(summary["realized_pnl_total"], 350.0, rel_tol=0, abs_tol=TOL)

    lots_after = _fetch_lots(conn)
    # Lot1 fully consumed; Lot2 has 5 remaining
    assert lots_after[0]["id"] == lot1_id and math.isclose(lots_after[0]["qty_remaining"], 0.0, rel_tol=0, abs_tol=TOL)
    assert lots_after[1]["id"] == lot2_id and math.isclose(lots_after[1]["qty_remaining"], 5.0, rel_tol=0, abs_tol=TOL)

    conn.close()


def test_short_fifo_cover_two_lots():
    """
    Open two short lots, cover across both FIFO, and validate:
      - qty_remaining is reduced correctly per lot
      - basis_total, proceeds_total (cover cash out), realized_pnl_total are correct
    Note: lots_engine.record_close computes short P&L as (cover_cost - basis) when pnl_fees_affect=False.
    """
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)

    # Open two short lots: (unit_cost = short proceeds/share baseline)
    # First short: 10 @ 50; Second short: 10 @ 40
    lot1_id = record_open(conn, symbol="MSFT", qty=10, unit_cost=50.0, side="short", fees=0.0, opened_trade_id="S1")
    lot2_id = record_open(conn, symbol="MSFT", qty=10, unit_cost=40.0, side="short", fees=0.0, opened_trade_id="S2")

    lots_before = _fetch_lots(conn)
    assert len(lots_before) == 2
    assert lots_before[0]["qty_remaining"] == 10
    assert lots_before[1]["qty_remaining"] == 10

    # Allocate FIFO to cover 15 shares
    allocs = allocate_for_close(conn, symbol="MSFT", qty_to_close=15, side="short", policy="FIFO")
    assert len(allocs) == 2
    assert allocs[0]["lot_id"] == lot1_id and math.isclose(allocs[0]["qty"], 10.0, rel_tol=0, abs_tol=TOL)
    assert allocs[1]["lot_id"] == lot2_id and math.isclose(allocs[1]["qty"], 5.0, rel_tol=0, abs_tol=TOL)

    # Cover 15 @ 45 → cover_cost (proceeds_total param) = 675; basis = 10*50 + 5*40 = 700
    # realized_pnl_total (per implementation) = cover_cost - basis = 675 - 700 = -25
    cover_cost = 15 * 45.0
    summary = record_close(
        conn,
        allocations=allocs,
        close_trade_id="S3",
        proceeds_total=cover_cost,   # cash OUT magnitude for cover
        total_close_fees=0.0,
        pnl_fees_affect=False,
    )
    assert math.isclose(summary["qty_closed"], 15.0, rel_tol=0, abs_tol=TOL)
    assert math.isclose(summary["basis_total"], 700.0, rel_tol=0, abs_tol=TOL)
    assert math.isclose(summary["proceeds_total"], 675.0, rel_tol=0, abs_tol=TOL)
    assert math.isclose(summary["realized_pnl_total"], -25.0, rel_tol=0, abs_tol=TOL)

    lots_after = _fetch_lots(conn)
    assert lots_after[0]["id"] == lot1_id and math.isclose(lots_after[0]["qty_remaining"], 0.0, rel_tol=0, abs_tol=TOL)
    assert lots_after[1]["id"] == lot2_id and math.isclose(lots_after[1]["qty_remaining"], 5.0, rel_tol=0, abs_tol=TOL)

    conn.close()
