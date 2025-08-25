# tbot_bot/accounting/ledger_modules/ledger_snapshot.py

"""
Daily/period ledger snapshots (v048)

- Snapshots balances and positions at UTC day boundaries.
- Idempotent per (snapshot_date_utc, entity, jurisdiction, broker, bot_id).
- Writes into snapshot tables within the primary ledger DB.
- Provides enqueue_snapshot(as_of_utc) and snapshot_day(date_utc) helpers.
- Retains pre-sync file snapshot (UTC + sync_run_id) with retention hooks.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

from tbot_bot.accounting.ledger_modules.ledger_core import get_conn
from tbot_bot.accounting.ledger_modules.ledger_balance import calculate_account_balances
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_snapshot_dir
from tbot_bot.support.utils_identity import get_bot_identity


# -----------------
# Time helpers
# -----------------

def _to_date_utc(date_like=None) -> datetime:
    """
    Accepts None|str|datetime; returns datetime at UTC midnight for that date.
    None -> today at UTC midnight.
    """
    if date_like is None:
        now = datetime.now(timezone.utc)
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    if isinstance(date_like, datetime):
        dt = date_like.astimezone(timezone.utc)
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if isinstance(date_like, str):
        # Accept 'YYYY-MM-DD' or full ISO; interpret in UTC
        try:
            if len(date_like) == 10:
                y, m, d = map(int, date_like.split("-"))
                return datetime(y, m, d, tzinfo=timezone.utc)
            dt = datetime.fromisoformat(date_like.replace("Z", "+00:00"))
            dt = dt.astimezone(timezone.utc)
            return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        except Exception:
            now = datetime.now(timezone.utc)
            return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _bounds_for_day(day_utc: datetime) -> Tuple[str, str, str]:
    """
    Returns (snapshot_date_utc 'YYYY-MM-DD', start_iso, end_iso) for the UTC day.
    """
    start = day_utc
    end = (day_utc + timedelta(days=1)) - timedelta(microseconds=1)
    return start.strftime("%Y-%m-%d"), start.isoformat(), end.isoformat()


# -----------------
# Schema helpers
# -----------------

DDL_BALANCES = """
CREATE TABLE IF NOT EXISTS daily_account_balances (
    snapshot_date_utc TEXT NOT NULL,
    entity_code       TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL,
    broker_code       TEXT NOT NULL,
    bot_id            TEXT NOT NULL,
    account           TEXT NOT NULL,
    opening_balance   REAL NOT NULL,
    debits            REAL NOT NULL,
    credits           REAL NOT NULL,
    closing_balance   REAL NOT NULL,
    created_at_utc    TEXT NOT NULL,
    updated_at_utc    TEXT NOT NULL,
    PRIMARY KEY (snapshot_date_utc, entity_code, jurisdiction_code, broker_code, bot_id, account)
);
"""

DDL_POSITIONS = """
CREATE TABLE IF NOT EXISTS daily_positions (
    snapshot_date_utc TEXT NOT NULL,
    entity_code       TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL,
    broker_code       TEXT NOT NULL,
    bot_id            TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    quantity          REAL NOT NULL,
    gross_cost        REAL,
    net_amount        REAL,
    created_at_utc    TEXT NOT NULL,
    updated_at_utc    TEXT NOT NULL,
    PRIMARY KEY (snapshot_date_utc, entity_code, jurisdiction_code, broker_code, bot_id, symbol)
);
"""


def _ensure_snapshot_tables() -> None:
    with get_conn() as conn:
        conn.executescript(DDL_BALANCES)
        conn.executescript(DDL_POSITIONS)


# -----------------
# Snapshot writers
# -----------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_day(date_utc: str | datetime | None = None) -> Tuple[int, int]:
    """
    Compute and write daily snapshots for the given UTC date.
    Returns (balances_rows_upserted, positions_rows_upserted).
    Idempotent per day+entity (UPSERT).
    """
    _ensure_snapshot_tables()

    # Identity (for keying rows; DBs are identity-scoped but we store explicitly)
    parts = str(get_bot_identity()).split("_")
    if len(parts) < 4:
        raise ValueError("Invalid BOT identity; expected 'ENTITY_JURISDICTION_BROKER_BOTID'")
    ec, jc, bc, bid = parts[0], parts[1], parts[2], parts[3]

    day = _to_date_utc(date_utc)
    snap_date, start_iso, end_iso = _bounds_for_day(day)
    now_iso = _utc_now_iso()

    # 1) Balances snapshot (reuse robust balance calculator)
    balances = calculate_account_balances(as_of_utc=end_iso, window_start_utc=start_iso)
    upsert_bal_sql = """
        INSERT INTO daily_account_balances
        (snapshot_date_utc, entity_code, jurisdiction_code, broker_code, bot_id, account,
         opening_balance, debits, credits, closing_balance, created_at_utc, updated_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date_utc, entity_code, jurisdiction_code, broker_code, bot_id, account)
        DO UPDATE SET
            opening_balance=excluded.opening_balance,
            debits=excluded.debits,
            credits=excluded.credits,
            closing_balance=excluded.closing_balance,
            updated_at_utc=excluded.updated_at_utc;
    """

    bal_rows = 0
    with get_conn() as conn:
        for account, vals in balances.items():
            conn.execute(
                upsert_bal_sql,
                (
                    snap_date,
                    ec,
                    jc,
                    bc,
                    bid,
                    account,
                    float(vals["opening_balance"]),
                    float(vals["debits"]),
                    float(vals["credits"]),
                    float(vals["closing_balance"]),
                    now_iso,
                    now_iso,
                ),
            )
            bal_rows += 1

    # 2) Positions snapshot (best-effort from splits)
    #    Quantity sign: debit->+, credit->-. If both legs carry qty, they net to zero.
    pos_sql = f"""
        SELECT symbol,
               SUM(CASE WHEN LOWER(COALESCE(side,''))='credit' THEN -COALESCE(quantity,0.0)
                        ELSE COALESCE(quantity,0.0) END) AS qty,
               SUM(COALESCE(total_value,0.0)) AS net_amount,
               SUM(CASE WHEN COALESCE(quantity,0.0) <> 0 THEN ABS(COALESCE(total_value,0.0)) ELSE 0 END) AS gross_cost
          FROM trades
         WHERE entity_code = ? AND jurisdiction_code = ? AND broker_code = ?
           AND COALESCE(symbol,'') <> ''
           AND COALESCE(quantity,0.0) IS NOT NULL
           AND COALESCE(timestamp_utc, datetime_utc, created_at_utc) <= ?
         GROUP BY symbol
         HAVING ABS(qty) > 0 OR ABS(net_amount) > 0
    """

    upsert_pos_sql = """
        INSERT INTO daily_positions
        (snapshot_date_utc, entity_code, jurisdiction_code, broker_code, bot_id, symbol,
         quantity, gross_cost, net_amount, created_at_utc, updated_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date_utc, entity_code, jurisdiction_code, broker_code, bot_id, symbol)
        DO UPDATE SET
            quantity=excluded.quantity,
            gross_cost=excluded.gross_cost,
            net_amount=excluded.net_amount,
            updated_at_utc=excluded.updated_at_utc;
    """

    pos_rows = 0
    with get_conn() as conn:
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute(pos_sql, (ec, jc, bc, end_iso)).fetchall()
        for r in rows:
            conn.execute(
                upsert_pos_sql,
                (
                    snap_date,
                    ec,
                    jc,
                    bc,
                    bid,
                    r["symbol"],
                    float(r["qty"] or 0.0),
                    float(r["gross_cost"] or 0.0),
                    float(r["net_amount"] or 0.0),
                    now_iso,
                    now_iso,
                ),
            )
            pos_rows += 1

    return bal_rows, pos_rows


def enqueue_snapshot(as_of_utc: str | None = None) -> Tuple[int, int]:
    """
    Public API used by hooks: snapshot the day corresponding to as_of_utc (or today).
    """
    day = _to_date_utc(as_of_utc)
    return snapshot_day(day)


# -----------------
# Pre-sync DB file snapshot (immutable, UTC + sync_run_id) with retention
# -----------------

def _list_snapshots(snapshot_dir: str) -> List[str]:
    return sorted(
        [f for f in os.listdir(snapshot_dir) if f.startswith("ledger_snapshot_") and f.endswith(".db")]
    )


def _enforce_snapshot_retention(snapshot_dir: str, keep: int) -> int:
    """
    Keep latest 'keep' snapshots by lexicographic order (UTC timestamp prefix ensures order).
    Returns number of files deleted.
    """
    try:
        files = _list_snapshots(snapshot_dir)
    except FileNotFoundError:
        return 0
    if keep <= 0 or len(files) <= keep:
        return 0
    to_delete = files[:-keep]
    deleted = 0
    for name in to_delete:
        try:
            os.remove(os.path.join(snapshot_dir, name))
            deleted += 1
        except Exception:
            # best-effort; continue
            pass
    return deleted


def snapshot_ledger_before_sync(sync_run_id: Optional[str] = None, keep_last: Optional[int] = None) -> str:
    """
    Atomically snapshot the current ledger DB file before sync/critical operation.
    Filename: ledger_snapshot_{UTC-TS}_{sync_run_id or 'nosync'}.db
    Retention: keep_last (defaults from env LEDGER_SNAPSHOT_KEEP or 20).
    """
    entity_code, jurisdiction_code, broker_code, bot_id = str(get_bot_identity()).split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    snapshot_dir = resolve_ledger_snapshot_dir(entity_code, jurisdiction_code, broker_code, bot_id)
    os.makedirs(snapshot_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sync_tag = (sync_run_id or "nosync").strip().replace(" ", "_")
    snapshot_name = f"ledger_snapshot_{ts}_{sync_tag}.db"
    snapshot_path = os.path.join(snapshot_dir, snapshot_name)

    # Atomic-ish copy (single write)
    with open(db_path, "rb") as src, open(snapshot_path, "wb") as dst:
        dst.write(src.read())

    # Retention
    if keep_last is None:
        try:
            keep_last = int(os.getenv("LEDGER_SNAPSHOT_KEEP", "20"))
        except Exception:
            keep_last = 20
    _enforce_snapshot_retention(snapshot_dir, max(0, int(keep_last)))

    return snapshot_path
