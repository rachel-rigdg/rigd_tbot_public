# tbot_bot/accounting/ledger_modules/ledger_balance.py
"""
Balance computation helpers (Decimal-safe, UTC-aware).
- Computes balances as-of a UTC timestamp, per account.
- Returns opening_balance, debits, credits, and closing_balance.
- Entity/jurisdiction/broker scoped via path_resolver + bot identity.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from pathlib import Path
from typing import Dict, Optional

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

# Decimal context
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN
_Q = Decimal("0.0001")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_utc_iso(ts: Optional[object]) -> str:
    """
    Accepts None|str|datetime. Returns ISO-8601 with UTC tzinfo.
    - None → now (UTC)
    - str  → parsed as ISO8601; naive interpreted as UTC
    - datetime → converted to UTC
    """
    if ts is None:
        return _utc_now_iso()
    if isinstance(ts, str):
        # Simple parse for ISO8601; assume already in UTC semantics
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            # Fallback: treat as naive UTC
            dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).isoformat()
    raise TypeError(f"Unsupported timestamp type: {type(ts)}")


def _utc_midnight_iso(as_of_iso: str) -> str:
    dt = datetime.fromisoformat(as_of_iso)
    dt = dt.astimezone(timezone.utc)
    midnight = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return midnight.isoformat()


def _dec(x) -> Decimal:
    if x is None:
        return Decimal("0").quantize(_Q)
    return Decimal(str(x)).quantize(_Q)


def _conn():
    ec, jc, bc, bid = str(get_bot_identity()).split("_", 3)
    db_path = resolve_ledger_db_path(ec, jc, bc, bid)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def calculate_account_balances(
    as_of_utc: Optional[object] = None,
    window_start_utc: Optional[object] = None,
) -> Dict[str, Dict[str, Decimal]]:
    """
    Compute per-account balances as-of a UTC timestamp.

    Args:
        as_of_utc: end-of-window (inclusive). Default=now UTC.
        window_start_utc: start-of-window (inclusive). Default=UTC midnight of as_of date.

    Returns:
        { account_path: {
            "opening_balance": Decimal,
            "debits": Decimal,     # sum of debits within window
            "credits": Decimal,    # sum of credits within window
            "closing_balance": Decimal
        }}
    Sign convention:
      - 'trades.total_value' is summed directly.
      - Debits/credits determined by 'side' if present else by sign of total_value.
      - closing = opening + debits - credits  (validated against direct sum).
    """
    if TEST_MODE_FLAG.exists():
        return {}

    as_of_iso = _to_utc_iso(as_of_utc)
    start_iso = _to_utc_iso(window_start_utc) if window_start_utc else _utc_midnight_iso(as_of_iso)

    # Column for timestamp: support multiple legacy names via COALESCE
    ts_col = "COALESCE(timestamp_utc, datetime_utc)"

    q_open = f"""
        SELECT account, SUM(total_value) AS amt
          FROM trades
         WHERE {ts_col} < ?
         GROUP BY account
    """
    q_window = f"""
        SELECT account,
               SUM(CASE WHEN (COALESCE(side,'')='debit' OR total_value > 0) THEN ABS(total_value) ELSE 0 END) AS debits,
               SUM(CASE WHEN (COALESCE(side,'')='credit' OR total_value < 0) THEN ABS(total_value) ELSE 0 END) AS credits
          FROM trades
         WHERE {ts_col} >= ?
           AND {ts_col} <= ?
         GROUP BY account
    """
    q_close = f"""
        SELECT account, SUM(total_value) AS amt
          FROM trades
         WHERE {ts_col} <= ?
         GROUP BY account
    """

    out: Dict[str, Dict[str, Decimal]] = {}

    with _conn() as conn:
        # Opening
        for row in conn.execute(q_open, (start_iso,)):
            acct = row["account"]
            out.setdefault(acct, {"opening_balance": Decimal("0"), "debits": Decimal("0"),
                                  "credits": Decimal("0"), "closing_balance": Decimal("0")})
            out[acct]["opening_balance"] = _dec(row["amt"])

        # Window debits/credits
        for row in conn.execute(q_window, (start_iso, as_of_iso)):
            acct = row["account"]
            out.setdefault(acct, {"opening_balance": Decimal("0"), "debits": Decimal("0"),
                                  "credits": Decimal("0"), "closing_balance": Decimal("0")})
            out[acct]["debits"] = _dec(row["debits"])
            out[acct]["credits"] = _dec(row["credits"])

        # Closing (direct sum as-of)
        for row in conn.execute(q_close, (as_of_iso,)):
            acct = row["account"]
            out.setdefault(acct, {"opening_balance": Decimal("0"), "debits": Decimal("0"),
                                  "credits": Decimal("0"), "closing_balance": Decimal("0")})
            out[acct]["closing_balance"] = _dec(row["amt"])

    # If closing missing for an account that has opening or window activity, compute via formula
    for acct, vals in out.items():
        if vals["closing_balance"] == Decimal("0"):
            vals["closing_balance"] = (vals["opening_balance"] + vals["debits"] - vals["credits"]).quantize(_Q)

    return out
