from __future__ import annotations
# tbot_bot/accounting/lots_engine.py
"""
Lot engine for position basis tracking (FIFO by default).
- Creates and maintains two tables: lots, lot_closures
- Supports long (side='long') and short (side='short') inventories
- Provides open, allocate, and close primitives
- UTC-only timestamps; OFX-friendly identifiers (opened_trade_id / close_trade_id)
- Immutable audit logging for opens/closes
"""

import sqlite3
from typing import List, Dict, Optional
from datetime import datetime, timezone

# Immutable audit (append-only)
from tbot_bot.accounting.ledger_modules.ledger_audit import append as audit_append

# --- Schema (kept here, but safe/idempotent and compatible with external migrations) ---
_LOTS_SQL = """
CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side   TEXT NOT NULL CHECK(side IN ('long','short')),
    qty_open      REAL NOT NULL,
    qty_remaining REAL NOT NULL,
    unit_cost     REAL NOT NULL,            -- For long: cost/share; For short: short-proceeds/share
    fees_alloc    REAL NOT NULL DEFAULT 0,  -- Aggregate fees allocated to this lot at open
    opened_trade_id TEXT,
    opened_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lots_symbol_side_remaining ON lots(symbol, side, qty_remaining);
"""

_CLOSURES_SQL = """
CREATE TABLE IF NOT EXISTS lot_closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL,
    close_trade_id TEXT,
    close_qty REAL NOT NULL,
    basis_amount REAL NOT NULL,     -- qty * unit_cost (+ optional fee apportioning)
    proceeds_amount REAL NOT NULL,  -- SELL cash in (long) or COVER cash out (short)
    fees_alloc REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL,
    closed_at TEXT NOT NULL,
    FOREIGN KEY(lot_id) REFERENCES lots(id)
);
CREATE INDEX IF NOT EXISTS idx_lot_closures_lot_id ON lot_closures(lot_id);
"""

def _utc_now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

def ensure_schema(conn: sqlite3.Connection) -> None:
    """
    Idempotent creation of lot tables + indexes.
    Enforces foreign keys and basic concurrency pragmas on the provided connection.
    """
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass

    cur = conn.cursor()
    cur.executescript(_LOTS_SQL)
    cur.executescript(_CLOSURES_SQL)
    conn.commit()

# ----------------------------
# OPEN / ALLOCATE / CLOSE
# ----------------------------
def record_open(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    qty: float,
    unit_cost: float,
    fees: float = 0.0,
    side: str = "long",
    opened_trade_id: Optional[str] = None,
    opened_at_iso: Optional[str] = None,
    actor: str = "system",
    audit: bool = True,
) -> int:
    """
    Insert an opening lot. For shorts, pass side='short' and unit_cost as short-proceeds/share.
    Returns new lot id.
    """
    assert side in ("long", "short"), "side must be 'long' or 'short'"
    if qty <= 0:
        raise ValueError("qty must be > 0 for a new lot")
    ts = opened_at_iso or _utc_now_iso()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO lots(symbol, side, qty_open, qty_remaining, unit_cost, fees_alloc, opened_trade_id, opened_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (symbol, side, float(qty), float(qty), float(unit_cost), float(fees or 0.0), opened_trade_id, ts),
    )
    conn.commit()
    lot_id = int(cur.lastrowid)

    if audit:
        try:
            audit_append(
                event_type="LOT_OPENED",
                related_id=lot_id,
                actor=actor or "system",
                before=None,
                after={"symbol": symbol, "side": side, "qty_open": qty, "unit_cost": unit_cost, "fees_alloc": float(fees or 0.0)},
                reason=None,
                extra={
                    "opened_trade_id": opened_trade_id,
                    "opened_at": ts,
                    "source": "lots_engine.record_open",
                },
            )
        except Exception:
            # Auditing failures must not break posting; upstream monitors will surface errors.
            pass

    return lot_id

def allocate_for_close(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    qty_to_close: float,
    side: str = "long",
    policy: str = "FIFO",
) -> List[Dict]:
    """
    Return a list of allocations (each referencing an open lot) sufficient to close qty_to_close.
    Each allocation dict: {lot_id, qty, unit_cost, fees_alloc, opened_at, opened_trade_id}
    For shorts, allocations will reference side='short' lots (short inventory).
    """
    assert side in ("long", "short")
    if qty_to_close <= 0:
        raise ValueError("qty_to_close must be > 0")

    cur = conn.cursor()
    order = "ASC" if policy.upper() == "FIFO" else "DESC"
    rows = cur.execute(
        f"""
        SELECT id, qty_remaining, unit_cost, fees_alloc, opened_at, opened_trade_id
        FROM lots
        WHERE symbol = ? AND side = ? AND qty_remaining > 0
        ORDER BY opened_at {order}, id {order}
        """,
        (symbol, side),
    ).fetchall()

    remaining = float(qty_to_close)
    allocations: List[Dict] = []
    for r in rows:
        if remaining <= 0:
            break
        take = min(remaining, float(r[1]))
        allocations.append({
            "lot_id": int(r[0]),
            "qty": float(take),
            "unit_cost": float(r[2]),
            "fees_alloc": float(r[3]),
            "opened_at": r[4],
            "opened_trade_id": r[5],
        })
        remaining -= take

    if remaining > 1e-10:  # insufficient lots
        raise ValueError(f"Insufficient inventory to close {qty_to_close} {side} {symbol}")
    return allocations

def record_close(
    conn: sqlite3.Connection,
    *,
    side: str,  # REQUIRED to compute realized P&L correctly ('long' sell vs 'short' cover)
    allocations: List[Dict],
    close_trade_id: Optional[str],
    proceeds_total: float,
    total_close_fees: float = 0.0,
    closed_at_iso: Optional[str] = None,
    pnl_fees_affect: bool = False,
    actor: str = "system",
    audit: bool = True,
) -> Dict:
    """
    Persist lot closures.

    For long SELL (side='long'):
      - proceeds_total is cash IN (positive).
      - realized_pnl = proceeds_total - sum(basis) - (fees if pnl_fees_affect)

    For short COVER (side='short'):
      - proceeds_total is cash OUT (positive cover cost).
      - basis is prior short proceeds locked at open.
      - realized_pnl = sum(basis) - proceeds_total - (fees if pnl_fees_affect)

    Returns summary dict with totals.
    """
    if side not in ("long", "short"):
        raise ValueError("side must be 'long' or 'short'")
    if not allocations:
        raise ValueError("allocations required")

    ts = closed_at_iso or _utc_now_iso()

    qty_total = sum(a["qty"] for a in allocations)
    basis_total = sum(a["qty"] * a["unit_cost"] for a in allocations)

    # Fee apportioning (pro-rata by qty)
    fee_rows = []
    for a in allocations:
        share = (a["qty"] / qty_total) if qty_total else 0.0
        fee_part = (total_close_fees or 0.0) * share
        fee_rows.append(fee_part)

    proceeds_rows = []
    for a in allocations:
        share = (a["qty"] / qty_total) if qty_total else 0.0
        proceeds_rows.append(proceeds_total * share)

    # Realized P&L per allocation (branch on side)
    realized_rows = []
    for i, a in enumerate(allocations):
        b = a["qty"] * a["unit_cost"]
        p = proceeds_rows[i]
        f = fee_rows[i]
        if side == "long":
            # SELL: cash in - basis - optional fees
            realized = (p - b) - (f if pnl_fees_affect else 0.0)
        else:
            # SHORT COVER: basis (short proceeds) - cash out - optional fees
            realized = (b - p) - (f if pnl_fees_affect else 0.0)
        realized_rows.append(realized)

    realized_total = sum(realized_rows)

    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        for i, a in enumerate(allocations):
            # Reduce qty_remaining
            cur.execute(
                "UPDATE lots SET qty_remaining = qty_remaining - ? WHERE id = ?",
                (float(a["qty"]), int(a["lot_id"]))
            )
            # Insert closure row
            cur.execute(
                """
                INSERT INTO lot_closures(lot_id, close_trade_id, close_qty, basis_amount,
                                         proceeds_amount, fees_alloc, realized_pnl, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(a["lot_id"]),
                    close_trade_id,
                    float(a["qty"]),
                    float(a["qty"] * a["unit_cost"]),
                    float(proceeds_rows[i]),
                    float(fee_rows[i]),
                    float(realized_rows[i]),
                    ts,
                ),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    if audit:
        try:
            audit_append(
                event_type="LOT_CLOSED",
                related_id=None,
                actor=actor or "system",
                before=None,
                after={
                    "side": side,
                    "qty_closed": float(qty_total),
                    "basis_total": float(basis_total),
                    "proceeds_total": float(proceeds_total),
                    "fees_total": float(total_close_fees or 0.0),
                    "realized_pnl_total": float(realized_total),
                },
                reason=None,
                extra={
                    "close_trade_id": close_trade_id,
                    "closed_at": ts,
                    "allocations_count": len(allocations),
                    "source": "lots_engine.record_close",
                },
            )
        except Exception:
            # Do not break main flow if audit logger has a transient issue.
            pass

    return {
        "side": side,
        "qty_closed": float(qty_total),
        "basis_total": float(basis_total),
        "proceeds_total": float(proceeds_total),
        "fees_total": float(total_close_fees or 0.0),
        "realized_pnl_total": float(realized_total),
        "closed_at": ts,
    }
