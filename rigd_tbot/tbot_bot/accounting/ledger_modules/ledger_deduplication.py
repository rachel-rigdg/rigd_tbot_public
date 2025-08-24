# tbot_bot/accounting/ledger_modules/ledger_deduplication.py

"""
Deduplication utilities (v048)
- Canonical dedupe key per entry: prefers FITID; falls back to composite.
- DB-level UNIQUE guards to enforce idempotency.
- Idempotent upsert helpers using SQLite ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_core import get_conn, tx_context
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.support.utils_identity import get_bot_identity

# Decimal context
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN

# ----------------------------
# Canonical dedupe key
# ----------------------------

_TS_KEYS = ("timestamp_utc", "datetime_utc", "created_at_utc")


def _norm_ts(e: Dict[str, Any]) -> str:
    """UTC ISO trimmed to seconds for stable keys."""
    for k in _TS_KEYS:
        v = e.get(k)
        if not v:
            continue
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    # Fallback stable empty
    return ""


def _norm_dec(x: Any) -> str:
    try:
        d = Decimal(str(x or "0")).quantize(Decimal("0.0001"))
    except Exception:
        d = Decimal("0.0000")
    # Use absolute magnitude for key; side encodes direction
    return f"{abs(d):f}"


def compute_dedupe_key(entry: Dict[str, Any]) -> str:
    """
    Canonical dedupe key:
      1) FITID if present (exact)
      2) Composite: {entity}:{juris}:{broker}:{trade_id}:{side}:{account}:{ts}:{amount}
    Note: DB is identity-scoped, but identity included to protect future merges.
    """
    fitid = (entry.get("fitid") or "").strip()
    if fitid:
        return f"FITID:{fitid}"

    # Identity (best-effort; safe defaults)
    parts = str(get_bot_identity()).split("_")
    entity = parts[0] if len(parts) > 0 else ""
    juris = parts[1] if len(parts) > 1 else ""
    broker = parts[2] if len(parts) > 2 else ""

    trade_id = str(entry.get("trade_id") or "").strip()
    side = str(entry.get("side") or "").strip().lower()
    account = str(entry.get("account") or "").strip()
    ts = _norm_ts(entry)
    amt = _norm_dec(entry.get("total_value"))

    return f"CMP:{entity}:{juris}:{broker}:{trade_id}:{side}:{account}:{ts}:{amt}"


# ----------------------------
# DB-level UNIQUE guards
# ----------------------------

def install_unique_guards() -> None:
    """
    Ensure additive schema + indexes needed for idempotency:
      a) Add missing columns via PRAGMA table_info(trades):
         - fitid TEXT
         - timestamp_utc TEXT
      b) Create UNIQUE index on (fitid) WHERE fitid IS NOT NULL
      c) Create index on (group_id)
      d) (Optional) Create composite UNIQUE index used by upsert when FITID is absent
         on (entity_code, jurisdiction_code, broker_code, trade_id, side, account, timestamp_utc)
    Never drops or renames anything; safe to call repeatedly.
    """
    with get_conn() as conn:
        # a) Check existing columns
        conn.row_factory = sqlite3.Row
        rows = conn.execute("PRAGMA table_info(trades)").fetchall()
        col_names = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}

        # Add columns if missing (additive only)
        if "fitid" not in col_names:
            try:
                conn.execute("ALTER TABLE trades ADD COLUMN fitid TEXT")
            except sqlite3.OperationalError as e:
                # Ignore if another process raced us
                if "duplicate column name" not in str(e).lower():
                    raise
        if "timestamp_utc" not in col_names:
            try:
                conn.execute("ALTER TABLE trades ADD COLUMN timestamp_utc TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise

        # b) Unique index on fitid (nullable allowed)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_fitid ON trades(fitid) WHERE fitid IS NOT NULL"
        )

        # c) Index on group_id for grouping queries
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_group_id ON trades(group_id)"
        )

        # d) Composite UNIQUE index to support ON CONFLICT() when FITID is absent
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS unique_trades_cmp
            ON trades(entity_code, jurisdiction_code, broker_code, trade_id, side, account, timestamp_utc)
            """
        )

        conn.commit()


# ----------------------------
# Idempotent upsert helpers
# ----------------------------

def _ordered_values(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    """Return values per TRADES_FIELDS order (missing keys → None)."""
    return tuple(entry.get(k) for k in TRADES_FIELDS)


def upsert_entry(entry: Dict[str, Any]) -> bool:
    """
    Insert a single row idempotently.
    - If fitid present: ON CONFLICT(fitid) DO NOTHING
    - Else: ON CONFLICT(entity_code, jurisdiction_code, broker_code, trade_id, side, account, timestamp_utc) DO NOTHING
    Returns True if inserted, False if skipped.
    Assumes caller has sanitized entry and ensured compliance.
    """
    has_fitid = bool(entry.get("fitid"))
    cols = ", ".join(TRADES_FIELDS)
    placeholders = ", ".join("?" for _ in TRADES_FIELDS)

    if has_fitid:
        sql = f"""
            INSERT INTO trades ({cols})
            VALUES ({placeholders})
            ON CONFLICT(fitid) DO NOTHING;
        """
    else:
        sql = f"""
            INSERT INTO trades ({cols})
            VALUES ({placeholders})
            ON CONFLICT(entity_code, jurisdiction_code, broker_code, trade_id, side, account, timestamp_utc)
            DO NOTHING;
        """

    with tx_context() as conn:
        cur = conn.execute(sql, _ordered_values(entry))
        # sqlite3 returns rowcount=1 on successful insert, 0 on DO NOTHING
        return cur.rowcount == 1


def upsert_entries(entries: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Batch idempotent insert.
    Returns: (inserted_count, skipped_count)
    """
    inserted = 0
    skipped = 0
    with tx_context() as conn:
        for e in entries:
            has_fitid = bool(e.get("fitid"))
            cols = ", ".join(TRADES_FIELDS)
            placeholders = ", ".join("?" for _ in TRADES_FIELDS)
            if has_fitid:
                sql = f"""
                    INSERT INTO trades ({cols})
                    VALUES ({placeholders})
                    ON CONFLICT(fitid) DO NOTHING;
                """
            else:
                sql = f"""
                    INSERT INTO trades ({cols})
                    VALUES ({placeholders})
                    ON CONFLICT(entity_code, jurisdiction_code, broker_code, trade_id, side, account, timestamp_utc)
                    DO NOTHING;
                """
            cur = conn.execute(sql, _ordered_values(e))
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


# ----------------------------
# Duplicate inspection/cleanup
# ----------------------------

def trade_exists(trade_id: str, side: Optional[str] = None) -> bool:
    """
    True if a trade with the given trade_id and optional side exists.
    """
    if not trade_id:
        return False
    q = "SELECT 1 FROM trades WHERE trade_id = ?"
    params: Tuple[Any, ...] = (trade_id,)
    if side:
        q += " AND side = ?"
        params = (trade_id, side)
    with get_conn() as conn:
        row = conn.execute(q + " LIMIT 1", params).fetchone()
        return row is not None


def check_duplicates(trade_id: str, side: Optional[str] = None) -> int:
    """
    Count duplicates for (trade_id[, side]).
    """
    if not trade_id:
        return 0
    q = "SELECT COUNT(*) FROM trades WHERE trade_id = ?"
    params: Tuple[Any, ...] = (trade_id,)
    if side:
        q += " AND side = ?"
        params = (trade_id, side)
    with get_conn() as conn:
        row = conn.execute(q, params).fetchone()
        return int(row[0]) if row else 0


def find_duplicate_trades(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    List (trade_id, side, count) pairs with count > 1.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT trade_id, side, COUNT(*) as count
              FROM trades
             WHERE trade_id IS NOT NULL
             GROUP BY trade_id, side
            HAVING count > 1
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [{"trade_id": r[0], "side": r[1], "count": r[2]} for r in rows]


def remove_duplicate_trades() -> int:
    """
    Deletes all but one of each duplicate (trade_id, side) pair.
    Returns number of deleted rows.
    """
    deleted = 0
    with tx_context() as conn:
        duplicates = conn.execute(
            """
            SELECT id
              FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (PARTITION BY trade_id, side ORDER BY id) AS rn
                      FROM trades
                     WHERE trade_id IS NOT NULL
                   )
             WHERE rn > 1
            """
        ).fetchall()
        ids = [row[0] for row in duplicates]
        if ids:
            conn.executemany("DELETE FROM trades WHERE id = ?", [(i,) for i in ids])
            deleted = len(ids)
    return deleted


# -------- In-memory dedup for pre-posting (sync/tests) --------

def deduplicate_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    In-memory deduplication before posting.
    Keeps the first occurrence of each canonical key (FITID or composite).
    Ensures group_id is populated with trade_id if missing.
    """
    seen = set()
    result: List[Dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        key = compute_dedupe_key(e)
        if key in seen:
            continue
        seen.add(key)
        if not e.get("group_id") and e.get("trade_id"):
            e = dict(e)
            e["group_id"] = e["trade_id"]
        result.append(e)
    return result
