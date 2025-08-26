# tbot_bot/accounting/ledger_modules/ledger_query.py
"""
Read-only ledger queries (v048, patched)

- Filterable queries: entity/jurisdiction/broker, date range, account, strategy, symbol, side, group_id.
- Stable ordering (time expr then id), works even if some *_utc columns are missing.
- Pagination via limit/offset.
- Returns typed rows (Decimals for numeric money-like fields; ISO-8601 UTC strings for timestamps).

Public API:
- query_entries(...)
- query_splits(...)          # alias of query_entries (explicit name for callers)
- query_balances(as_of_utc=None, window_start_utc=None)
- fetch_grouped_trades(...)
- fetch_trade_group_by_id(...)
- search_trades(...)         # compatibility wrapper for web UI
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from typing import Any, Dict, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_core import get_conn, get_identity_tuple
from tbot_bot.accounting.ledger_modules.ledger_grouping import (
    fetch_grouped_trades as grouping_fetch_grouped_trades,
    fetch_trade_group_by_id as grouping_fetch_trade_group_by_id,
)

# Decimal policy
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN
_Q = Decimal("0.0001")

# -----------------
# Utilities
# -----------------

_NUMERIC_FIELDS = {
    "quantity", "price", "total_value", "amount", "commission", "fee",
    "fx_rate", "accrued_interest", "tax", "net_amount",
}

_TS_FIELDS = {
    "timestamp_utc", "datetime_utc", "created_at_utc", "updated_at_utc",
    "trade_date", "settlement_date", "DTPOSTED", "posted_at_utc"
}


def _to_dec(x: Any) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        return Decimal(str(x)).quantize(_Q)
    except Exception:
        return None


def _to_iso_utc(s: Any) -> Optional[str]:
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _row_to_typed(row: sqlite3.Row) -> Dict[str, Any]:
    d = {k: row[k] for k in row.keys()}
    for k in list(d.keys()):
        if k in _NUMERIC_FIELDS and d[k] is not None:
            d[k] = _to_dec(d[k])
        elif k in _TS_FIELDS and d[k] is not None:
            iso = _to_iso_utc(d[k])
            d[k] = iso if iso is not None else d[k]
    return d


def _existing_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cols: List[str] = []
    for r in conn.execute(f"PRAGMA table_info({table})").fetchall():
        try:
            cols.append(r[1])  # name
        except Exception:
            pass
    return [c for c in cols if c]


def _resolve_ts_expr(conn: sqlite3.Connection, table: str = "trades") -> str:
    """
    Build a timestamp expression using only columns that actually exist,
    preferring canonical UTC fields but falling back to OFX DTPOSTED, etc.
    Safe for ORDER BY and WHERE.
    """
    candidates = ["timestamp_utc", "datetime_utc", "created_at_utc", "DTPOSTED", "posted_at_utc"]
    present_set = set(_existing_columns(conn, table))
    present = [c for c in candidates if c in present_set]
    if not present:
        # Fall back to a constant so ORDER BY <const>, id is still valid SQL.
        return "''"
    if len(present) == 1:
        return present[0]
    return "COALESCE(" + ", ".join(present) + ")"


def _apply_identity_defaults(filters: Dict[str, Any]) -> Tuple[str, str, str]:
    ec, jc, bc, _ = get_identity_tuple()
    return (
        filters.get("entity_code") or ec,
        filters.get("jurisdiction_code") or jc,
        filters.get("broker_code") or bc,
    )


def _build_where_and_params(filters: Dict[str, Any], ts_expr: str) -> Tuple[str, List[Any]]:
    where: List[str] = []
    params: List[Any] = []

    # Identity scope (defaults to current identity)
    ec, jc, bc = _apply_identity_defaults(filters)
    where += ["entity_code = ?", "jurisdiction_code = ?", "broker_code = ?"]
    params += [ec, jc, bc]

    # Date range (inclusive)
    start = filters.get("start_utc")
    end = filters.get("end_utc")
    if start:
        where.append(f"{ts_expr} >= ?")
        params.append(start)
    if end:
        where.append(f"{ts_expr} <= ?")
        params.append(end)

    # Account filter (prefix/LIKE)
    account = filters.get("account")
    if account:
        if "%" in account or "_" in account:
            where.append("account LIKE ?")
            params.append(account)
        else:
            where.append("account LIKE ?")
            params.append(f"{account}%")

    # Strategy, Symbol, Side, Group, Trade
    if filters.get("strategy"):
        where.append("strategy = ?")
        params.append(filters["strategy"])
    if filters.get("symbol"):
        where.append("symbol = ?")
        params.append(filters["symbol"])
    if filters.get("side"):
        where.append("LOWER(side) = LOWER(?)")
        params.append(filters["side"])
    if filters.get("group_id"):
        where.append("group_id = ?")
        params.append(filters["group_id"])
    if filters.get("trade_id"):
        where.append("trade_id = ?")
        params.append(filters["trade_id"])

    # Free-text search (limited columns)
    if filters.get("search"):
        like = f"%{filters['search']}%"
        where.append("(symbol LIKE ? OR trade_id LIKE ? OR description LIKE ? OR tags LIKE ?)")
        params += [like, like, like, like]

    clause = "WHERE " + " AND ".join(where) if where else ""
    return clause, params


def _order_clause(ts_expr: str, sort_desc: bool) -> str:
    return f"ORDER BY {ts_expr} {'DESC' if sort_desc else 'ASC'}, id {'DESC' if sort_desc else 'ASC'}"


# -----------------
# Public query APIs
# -----------------

def query_entries(
    *,
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    start_utc: Optional[str] = None,
    end_utc: Optional[str] = None,
    account: Optional[str] = None,
    strategy: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    group_id: Optional[str] = None,
    trade_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    sort_desc: bool = True,
) -> List[Dict[str, Any]]:
    """
    Read-only fetch from trades with filters and pagination.
    Returns typed dict rows.
    """
    filters = {
        "entity_code": entity_code,
        "jurisdiction_code": jurisdiction_code,
        "broker_code": broker_code,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "account": account,
        "strategy": strategy,
        "symbol": symbol,
        "side": side,
        "group_id": group_id,
        "trade_id": trade_id,
        "search": search,
    }

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        ts_expr = _resolve_ts_expr(conn, "trades")
        where, params = _build_where_and_params(filters, ts_expr)
        order = _order_clause(ts_expr, sort_desc)

        cols = "*"
        sql = f"SELECT {cols} FROM trades {where} {order} LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]

        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_typed(r) for r in rows]


def query_splits(**kwargs) -> List[Dict[str, Any]]:
    """Alias for query_entries; callers may conceptually think in 'splits'."""
    return query_entries(**kwargs)


def query_balances(
    *,
    as_of_utc: Optional[str] = None,
    window_start_utc: Optional[str] = None,
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Per-account balances as of a UTC timestamp, including opening/debits/credits/closing.
    (Computed from trades totals; if you later migrate to a splits table, switch sums accordingly.)
    """
    # Identity scope
    ec, jc, bc = _apply_identity_defaults(
        {"entity_code": entity_code, "jurisdiction_code": jurisdiction_code, "broker_code": broker_code}
    )

    # Time bounds
    as_of = as_of_utc or datetime.now(timezone.utc).isoformat()
    start = window_start_utc
    if not start:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00")).astimezone(timezone.utc)
        start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).isoformat()

    out: Dict[str, Dict[str, Any]] = {}

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        ts_expr = _resolve_ts_expr(conn, "trades")

        q_open = f"""
            SELECT account, SUM(total_value) AS amt
              FROM trades
             WHERE entity_code = ? AND jurisdiction_code = ? AND broker_code = ?
               AND {ts_expr} < ?
             GROUP BY account
        """
        q_window = f"""
            SELECT account,
                   SUM(CASE WHEN (LOWER(COALESCE(side,''))='debit' OR total_value > 0) THEN ABS(total_value) ELSE 0 END) AS debits,
                   SUM(CASE WHEN (LOWER(COALESCE(side,''))='credit' OR total_value < 0) THEN ABS(total_value) ELSE 0 END) AS credits
              FROM trades
             WHERE entity_code = ? AND jurisdiction_code = ? AND broker_code = ?
               AND {ts_expr} >= ?
               AND {ts_expr} <= ?
             GROUP BY account
        """
        q_close = f"""
            SELECT account, SUM(total_value) AS amt
              FROM trades
             WHERE entity_code = ? AND jurisdiction_code = ? AND broker_code = ?
               AND {ts_expr} <= ?
             GROUP BY account
        """

        for r in conn.execute(q_open, (ec, jc, bc, start)).fetchall():
            acct = r["account"]
            out.setdefault(acct, {"account": acct, "opening_balance": Decimal("0"), "debits": Decimal("0"),
                                  "credits": Decimal("0"), "closing_balance": Decimal("0")})
            out[acct]["opening_balance"] = _to_dec(r["amt"]) or Decimal("0")

        for r in conn.execute(q_window, (ec, jc, bc, start, as_of)).fetchall():
            acct = r["account"]
            out.setdefault(acct, {"account": acct, "opening_balance": Decimal("0"), "debits": Decimal("0"),
                                  "credits": Decimal("0"), "closing_balance": Decimal("0")})
            out[acct]["debits"] = _to_dec(r["debits"]) or Decimal("0")
            out[acct]["credits"] = _to_dec(r["credits"]) or Decimal("0")

        for r in conn.execute(q_close, (ec, jc, bc, as_of)).fetchall():
            acct = r["account"]
            out.setdefault(acct, {"account": acct, "opening_balance": Decimal("0"), "debits": Decimal("0"),
                                  "credits": Decimal("0"), "closing_balance": Decimal("0")})
            out[acct]["closing_balance"] = _to_dec(r["amt"]) or Decimal("0")

    # Compute missing closings via formula if needed
    rows: List[Dict[str, Any]] = []
    for acct, vals in sorted(out.items(), key=lambda kv: kv[0]):
        if vals["closing_balance"] == Decimal("0"):
            vals["closing_balance"] = (vals["opening_balance"] + vals["debits"] - vals["credits"]).quantize(_Q)
        rows.append(
            {
                "account": acct,
                "opening_balance": vals["opening_balance"].quantize(_Q),
                "debits": vals["debits"].quantize(_Q),
                "credits": vals["credits"].quantize(_Q),
                "closing_balance": vals["closing_balance"].quantize(_Q),
            }
        )
    return rows


# -----------------
# Grouping re-exports
# -----------------

def fetch_grouped_trades(*args, **kwargs):
    return grouping_fetch_grouped_trades(*args, **kwargs)


def fetch_trade_group_by_id(group_id, *args, **kwargs):
    return grouping_fetch_trade_group_by_id(group_id, *args, **kwargs)


# -----------------
# Web/UI compatibility shim
# -----------------

def search_trades(
    *,
    search_term: Optional[str] = None,
    sort_by: str = "datetime_utc",   # accepted but ordering is fixed to time expr then id
    sort_desc: bool = True,
    limit: int = 1000,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Backward/compat wrapper used by web UI.
    Delegates to query_entries() with free-text 'search' applied.
    """
    return query_entries(search=search_term or None, limit=limit, offset=offset, sort_desc=sort_desc)
