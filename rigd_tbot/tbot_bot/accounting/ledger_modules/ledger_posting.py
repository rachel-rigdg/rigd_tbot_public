# tbot_bot/accounting/ledger_modules/ledger_posting.py
"""
Posting router that converts normalized broker trades into multi-leg ledger entries
using the lots engine for cost-basis and realized P&L.

Conventions:
- Positive total_value = Debit; Negative total_value = Credit
- Fees are expensed to Brokerage Fees (by default NOT deducted from realized P&L)
- All timestamps are UTC ISO-8601
"""

from __future__ import annotations
import sqlite3
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_coa_json_path
from tbot_bot.accounting.ledger_modules.ledger_audit import append as audit_append
from tbot_bot.accounting.lots_engine import (
    ensure_schema as lots_ensure_schema,
    record_open,
    allocate_for_close,
    record_close,
)

# Optional: reference the trade field list dynamically
try:
    from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS as _TRADES_FIELDS
except Exception:  # pragma: no cover
    _TRADES_FIELDS = []  # dynamic insert will inspect DB columns instead

# ----------------------------
# Config / Accounts
# ----------------------------
FEES_AFFECT_REALIZED_PNL = False  # set True if you want fees included in realized P&L math
ROUND_DECIMALS = 2

# Default account labels (must match your COA; will be overridden when possible by COA discovery)
DEFAULT_ACCOUNTS: Dict[str, str] = {
    "cash": "Assets:Brokerage:Cash",
    "equity_prefix": "Assets:Brokerage:Equity:",          # + SYMBOL
    "short_prefix": "Liabilities:Short Positions:",        # + SYMBOL
    "fees": "Expenses:Brokerage Fees",
    "realized_pnl": "Income:Realized Gains – Equities",    # 4010-equivalent
    "dividends": "Income:Dividends Earned",
    "interest": "Income:Interest Income",
    "equity_contrib": "Equity:Capital Contributions",
    "owner_withdrawals": "Equity:Owner Withdrawals",
}

def _utc_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

def _connect() -> sqlite3.Connection:
    e, j, b, bot_id = (load_bot_identity() or "X_X_X_X").split("_")
    path = resolve_ledger_db_path(e, j, b, bot_id)
    conn = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def _db_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cols = []
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        cols.append(row[1])
    return cols

def _coalesce_accounts() -> Dict[str, str]:
    """
    Try to read the COA JSON and find best-fit names; fall back to DEFAULT_ACCOUNTS.
    We match by keywords in account names to be tolerant to prefixes or numbering.
    """
    acc = dict(DEFAULT_ACCOUNTS)
    try:
        import json
        p = resolve_coa_json_path()
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        nodes = data.get("accounts") if isinstance(data, dict) else data

        found: Dict[str, str] = {}

        def pick(key: str, full: str, is_prefix: bool = False):
            if key in found:
                return
            found[key] = full + (":" if is_prefix and not full.endswith(":") else "")

        def walk(a, path=""):
            for n in a or []:
                name = (n.get("name") or n.get("title") or n.get("label") or n.get("code") or "").strip()
                full = (path + name).strip(":")
                lower = full.lower()

                # Cash
                if "broker" in lower and "cash" in lower:
                    pick("cash", full)

                # Equities / short
                if ("broker" in lower or "brokerage" in lower) and ("equities" in lower or "equity" in lower or "stock" in lower):
                    pick("equity_prefix", full, is_prefix=True)
                if "short" in lower and ("liab" in lower or "position" in lower or "positions" in lower):
                    pick("short_prefix", full, is_prefix=True)

                # Income + fees
                if "realized" in lower and "gain" in lower:
                    pick("realized_pnl", full)
                if "dividend" in lower:
                    pick("dividends", full)
                if "interest" in lower:
                    pick("interest", full)
                if "broker fee" in lower or "brokerage fee" in lower or "commission" in lower:
                    pick("fees", full)

                # Equity movements
                if "capital" in lower and "contribution" in lower:
                    pick("equity_contrib", full)
                if "owner" in lower and "withdraw" in lower:
                    pick("owner_withdrawals", full)

                kids = n.get("children") or []
                if kids:
                    walk(kids, full + ":")
        walk(nodes or [])
        acc.update(found)
    except Exception:
        pass
    return acc

def _equity_acct(acc_map: Dict[str, str], symbol: Optional[str]) -> str:
    return f"{acc_map['equity_prefix']}{(symbol or 'UNKNOWN').upper()}"

def _short_acct(acc_map: Dict[str, str], symbol: Optional[str]) -> str:
    return f"{acc_map['short_prefix']}{(symbol or 'UNKNOWN').upper()}"

# ----------------------------
# Insertion helper
# ----------------------------
def _insert_legs(conn: sqlite3.Connection, legs: List[Dict[str, Any]]) -> None:
    cols_available = set(_db_columns(conn, "trades"))
    # If TRADES_FIELDS is known, intersect with table cols to preserve order
    ordered_cols = [c for c in _TRADES_FIELDS if c in cols_available] if _TRADES_FIELDS else [c for c in cols_available]
    if "id" in ordered_cols:
        ordered_cols.remove("id")

    placeholders = ", ".join("?" for _ in ordered_cols)
    sql = f"INSERT INTO trades ({', '.join(ordered_cols)}) VALUES ({placeholders})"

    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        for leg in legs:
            row = {k: leg.get(k) for k in ordered_cols}
            # Fill some common defaults if missing
            row.setdefault("datetime_utc", _utc_iso())
            row.setdefault("approval_status", "approved")
            row.setdefault("gdpr_compliant", True)
            row.setdefault("ccpa_compliant", True)
            row.setdefault("pipeda_compliant", True)
            row.setdefault("hipaa_sensitive", False)
            # created/updated_by best effort
            actor = leg.get("created_by") or leg.get("updated_by") or "system"
            row.setdefault("created_by", actor)
            row.setdefault("updated_by", actor)
            cur.execute(sql, [row.get(c) for c in ordered_cols])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

# ----------------------------
# Public posting APIs (trades)
# ----------------------------
def post_buy(
    *,
    symbol: str,
    qty: float,
    price: float,
    fee: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Long BUY:
      Dr Equity {SYM}            +qty*price
      Cr Cash                    -(qty*price)
      Dr Fees                    +fee
      Cr Cash                    -fee
      Open lot at unit_cost=price
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    strategy = meta.get("strategy")
    tags = meta.get("tags")
    ts = ts_utc or _utc_iso()
    amt = round(qty * price, ROUND_DECIMALS)

    acc = _coalesce_accounts()

    # DB
    conn = _connect()
    lots_ensure_schema(conn)

    # Open lot at raw price (fees handled as expense)
    record_open(
        conn,
        symbol=symbol,
        qty=qty,
        unit_cost=price,
        fees=0.0,
        side="long",
        opened_trade_id=trade_id,
        opened_at_iso=ts,
    )

    legs = [
        dict(datetime_utc=ts, symbol=symbol, action="BUY_EQUITY",   account=_equity_acct(acc, symbol),
             total_value=+amt, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="BUY equity (debit)"),
        dict(datetime_utc=ts, symbol=symbol, action="BUY_CASH",     account=acc["cash"],
             total_value=-amt, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="BUY cash (credit)"),
    ]
    if fee and fee != 0:
        legs += [
            dict(datetime_utc=ts, symbol=symbol, action="FEE_EXPENSE", account=acc["fees"],
                 total_value=+round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee (debit)"),
            dict(datetime_utc=ts, symbol=symbol, action="FEE_CASH", account=acc["cash"],
                 total_value=-round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee cash (credit)"),
        ]

    _insert_legs(conn, legs)
    audit_append(event="TRADE_POSTED_LONG_BUY", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"qty": qty, "price": price, "fee": fee}, reason="post_buy")
    conn.close()
    return {"ok": True, "legs": len(legs)}

def post_sell(
    *,
    symbol: str,
    qty: float,
    price: float,
    fee: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Close LONG (SELL):
      Dr Cash                         +proceeds
      Cr Equity {SYM}                 -basis (per lots)
      Realized P&L to Income (4010):
        gain => Credit (negative value)
        loss => Debit (positive value)
      Fees expensed separate
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    strategy = meta.get("strategy")
    tags = meta.get("tags")
    ts = ts_utc or _utc_iso()

    acc = _coalesce_accounts()
    proceeds = round(qty * price, ROUND_DECIMALS)

    conn = _connect()
    lots_ensure_schema(conn)

    allocations = allocate_for_close(conn, symbol=symbol, qty_to_close=qty, side="long", policy="FIFO")
    summary = record_close(
        conn,
        allocations=allocations,
        close_trade_id=trade_id,
        proceeds_total=proceeds,
        total_close_fees=fee or 0.0,
        closed_at_iso=ts,
        pnl_fees_affect=FEES_AFFECT_REALIZED_PNL,
    )

    basis = round(summary["basis_total"], ROUND_DECIMALS)
    realized = round(summary["realized_pnl_total"], ROUND_DECIMALS)

    legs = [
        dict(datetime_utc=ts, symbol=symbol, action="SELL_CASH",   account=acc["cash"],
             total_value=+proceeds, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="SELL proceeds (debit cash)"),
        dict(datetime_utc=ts, symbol=symbol, action="SELL_BASIS",  account=_equity_acct(acc, symbol),
             total_value=-basis, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="SELL remove basis (credit equity)"),
    ]
    # P&L leg: credit negative for gains, debit positive for losses
    if realized != 0:
        legs.append(
            dict(datetime_utc=ts, symbol=symbol, action="REALIZED_PNL", account=acc["realized_pnl"],
                 total_value=(-realized if realized > 0 else +abs(realized)),
                 group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Realized P&L on SELL")
        )
    if fee and fee != 0:
        legs += [
            dict(datetime_utc=ts, symbol=symbol, action="FEE_EXPENSE", account=acc["fees"],
                 total_value=+round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee (debit)"),
            dict(datetime_utc=ts, symbol=symbol, action="FEE_CASH", account=acc["cash"],
                 total_value=-round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee cash (credit)"),
        ]

    _insert_legs(conn, legs)
    audit_append(event="TRADE_POSTED_LONG_SELL", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"qty": qty, "price": price, "fee": fee, "pnl": realized}, reason="post_sell")
    conn.close()
    return {"ok": True, "legs": len(legs), "basis": basis, "proceeds": proceeds, "realized": realized}

def post_short_open(
    *,
    symbol: str,
    qty: float,
    price: float,
    fee: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Open SHORT (sell to open):
      Dr Cash                              +short proceeds
      Cr Liabilities:Short Positions:SYM   -short proceeds
      Fees expensed
      Lot opened with unit_cost = short proceeds/share
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    strategy = meta.get("strategy")
    tags = meta.get("tags")
    ts = ts_utc or _utc_iso()

    acc = _coalesce_accounts()
    proceeds = round(qty * price, ROUND_DECIMALS)

    conn = _connect()
    lots_ensure_schema(conn)

    # For short lots, we treat unit_cost as the short proceeds/share baseline
    record_open(
        conn,
        symbol=symbol,
        qty=qty,
        unit_cost=price,
        fees=0.0,
        side="short",
        opened_trade_id=trade_id,
        opened_at_iso=ts,
    )

    legs = [
        dict(datetime_utc=ts, symbol=symbol, action="SHORT_OPEN_CASH", account=acc["cash"],
             total_value=+proceeds, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="SHORT open: receive proceeds (debit cash)"),
        dict(datetime_utc=ts, symbol=symbol, action="SHORT_OPEN_LIAB", account=_short_acct(acc, symbol),
             total_value=-proceeds, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="SHORT open: liability (credit)"),
    ]
    if fee and fee != 0:
        legs += [
            dict(datetime_utc=ts, symbol=symbol, action="FEE_EXPENSE", account=acc["fees"],
                 total_value=+round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee (debit)"),
            dict(datetime_utc=ts, symbol=symbol, action="FEE_CASH", account=acc["cash"],
                 total_value=-round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee cash (credit)"),
        ]

    _insert_legs(conn, legs)
    audit_append(event="TRADE_POSTED_SHORT_OPEN", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"qty": qty, "price": price, "fee": fee}, reason="post_short_open")
    conn.close()
    return {"ok": True, "legs": len(legs)}

def post_short_cover(
    *,
    symbol: str,
    qty: float,
    price: float,
    fee: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Close SHORT (buy to cover):
      Dr Liabilities:Short Positions:SYM   +basis (remove liability)
      Cr Cash                               -cover cost
      P&L: (basis - cover_cost) to Income (4010)
      Fees expensed
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    strategy = meta.get("strategy")
    tags = meta.get("tags")
    ts = ts_utc or _utc_iso()

    acc = _coalesce_accounts()
    cover_cost = round(qty * price, ROUND_DECIMALS)

    conn = _connect()
    lots_ensure_schema(conn)

    allocations = allocate_for_close(conn, symbol=symbol, qty_to_close=qty, side="short", policy="FIFO")
    # For shorts, we feed proceeds_total = cover cash OUT (positive magnitude)
    summary = record_close(
        conn,
        allocations=allocations,
        close_trade_id=trade_id,
        proceeds_total=cover_cost,
        total_close_fees=fee or 0.0,
        closed_at_iso=ts,
        pnl_fees_affect=FEES_AFFECT_REALIZED_PNL,
    )

    basis = round(summary["basis_total"], ROUND_DECIMALS)
    realized = round(summary["realized_pnl_total"], ROUND_DECIMALS)  # >0 gain; <0 loss

    legs = [
        dict(datetime_utc=ts, symbol=symbol, action="SHORT_COVER_LIAB", account=_short_acct(acc, symbol),
             total_value=+basis, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="SHORT cover: remove liability (debit)"),
        dict(datetime_utc=ts, symbol=symbol, action="SHORT_COVER_CASH", account=acc["cash"],
             total_value=-cover_cost, group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
             notes="SHORT cover: pay cash (credit)"),
    ]
    if realized != 0:
        # Gain -> credit (negative); Loss -> debit (positive)
        legs.append(
            dict(datetime_utc=ts, symbol=symbol, action="REALIZED_PNL_SHORT", account=acc["realized_pnl"],
                 total_value=(-realized if realized > 0 else +abs(realized)),
                 group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Realized P&L on SHORT cover")
        )
    if fee and fee != 0:
        legs += [
            dict(datetime_utc=ts, symbol=symbol, action="FEE_EXPENSE", account=acc["fees"],
                 total_value=+round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee (debit)"),
            dict(datetime_utc=ts, symbol=symbol, action="FEE_CASH", account=acc["cash"],
                 total_value=-round(fee, ROUND_DECIMALS), group_id=group_id, trade_id=trade_id, strategy=strategy, tags=tags,
                 notes="Brokerage fee cash (credit)"),
        ]

    _insert_legs(conn, legs)
    audit_append(event="TRADE_POSTED_SHORT_COVER", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"qty": qty, "price": price, "fee": fee, "pnl": realized}, reason="post_short_cover")
    conn.close()
    return {"ok": True, "legs": len(legs), "basis": basis, "cover_cost": cover_cost, "realized": realized}

# ----------------------------
# Non-trade postings (cash/admin events)
# ----------------------------
def post_deposit(
    *,
    amount: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Cash DEPOSIT (owner contribution):
      Dr Cash                               +amount
      Cr Equity:Capital Contributions       -amount
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    ts = ts_utc or _utc_iso()
    amt = round(float(amount), ROUND_DECIMALS)
    acc = _coalesce_accounts()

    conn = _connect()
    legs = [
        dict(datetime_utc=ts, action="DEPOSIT_CASH", account=acc["cash"],
             total_value=+amt, group_id=group_id, trade_id=trade_id, notes="Deposit received"),
        dict(datetime_utc=ts, action="DEPOSIT_EQUITY", account=acc["equity_contrib"],
             total_value=-amt, group_id=group_id, trade_id=trade_id, notes="Owner contribution"),
    ]
    _insert_legs(conn, legs)
    audit_append(event="CASH_DEPOSIT", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"amount": amt}, reason="post_deposit")
    conn.close()
    return {"ok": True, "legs": len(legs)}

def post_withdrawal(
    *,
    amount: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Cash WITHDRAWAL (owner draw):
      Dr Equity:Owner Withdrawals           +amount
      Cr Cash                               -amount
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    ts = ts_utc or _utc_iso()
    amt = round(float(amount), ROUND_DECIMALS)
    acc = _coalesce_accounts()

    conn = _connect()
    legs = [
        dict(datetime_utc=ts, action="WITHDRAWAL_EQUITY", account=acc["owner_withdrawals"],
             total_value=+amt, group_id=group_id, trade_id=trade_id, notes="Owner withdrawal"),
        dict(datetime_utc=ts, action="WITHDRAWAL_CASH", account=acc["cash"],
             total_value=-amt, group_id=group_id, trade_id=trade_id, notes="Withdrawal cash"),
    ]
    _insert_legs(conn, legs)
    audit_append(event="CASH_WITHDRAWAL", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"amount": amt}, reason="post_withdrawal")
    conn.close()
    return {"ok": True, "legs": len(legs)}

def post_dividend(
    *,
    amount: float,
    trade_id: str,
    symbol: Optional[str] = None,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    DIVIDEND:
      Dr Cash                               +amount
      Cr Income:Dividends                   -amount
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    ts = ts_utc or _utc_iso()
    amt = round(float(amount), ROUND_DECIMALS)
    acc = _coalesce_accounts()

    conn = _connect()
    legs = [
        dict(datetime_utc=ts, symbol=symbol, action="DIVIDEND_CASH", account=acc["cash"],
             total_value=+amt, group_id=group_id, trade_id=trade_id, notes="Dividend received"),
        dict(datetime_utc=ts, symbol=symbol, action="DIVIDEND_INCOME", account=acc["dividends"],
             total_value=-amt, group_id=group_id, trade_id=trade_id, notes="Dividend income"),
    ]
    _insert_legs(conn, legs)
    audit_append(event="DIVIDEND_POSTED", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"amount": amt, "symbol": symbol}, reason="post_dividend")
    conn.close()
    return {"ok": True, "legs": len(legs)}

def post_interest(
    *,
    amount: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    INTEREST:
      Dr Cash                               +amount
      Cr Income:Interest                    -amount
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    ts = ts_utc or _utc_iso()
    amt = round(float(amount), ROUND_DECIMALS)
    acc = _coalesce_accounts()

    conn = _connect()
    legs = [
        dict(datetime_utc=ts, action="INTEREST_CASH", account=acc["cash"],
             total_value=+amt, group_id=group_id, trade_id=trade_id, notes="Interest received"),
        dict(datetime_utc=ts, action="INTEREST_INCOME", account=acc["interest"],
             total_value=-amt, group_id=group_id, trade_id=trade_id, notes="Interest income"),
    ]
    _insert_legs(conn, legs)
    audit_append(event="INTEREST_POSTED", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"amount": amt}, reason="post_interest")
    conn.close()
    return {"ok": True, "legs": len(legs)}

def post_fee(
    *,
    amount: float,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    FEE / COMMISSION:
      Dr Expenses:Brokerage Fees            +amount
      Cr Cash                               -amount
    """
    meta = meta or {}
    actor = meta.get("actor") or "system"
    group_id = meta.get("group_id") or trade_id
    ts = ts_utc or _utc_iso()
    amt = round(float(amount), ROUND_DECIMALS)
    acc = _coalesce_accounts()

    conn = _connect()
    legs = [
        dict(datetime_utc=ts, action="FEE_EXPENSE", account=acc["fees"],
             total_value=+amt, group_id=group_id, trade_id=trade_id, notes="Broker fee (debit)"),
        dict(datetime_utc=ts, action="FEE_CASH", account=acc["cash"],
             total_value=-amt, group_id=group_id, trade_id=trade_id, notes="Broker fee cash (credit)"),
    ]
    _insert_legs(conn, legs)
    audit_append(event="FEE_POSTED", related_id=trade_id, actor=actor, group_id=group_id,
                 before=None, after={"amount": amt}, reason="post_fee")
    conn.close()
    return {"ok": True, "legs": len(legs)}

# Back-compat alias
def post_commission(**kwargs) -> Dict[str, Any]:
    return post_fee(**kwargs)

# ----------------------------
# Generic router (optional convenience)
# ----------------------------
def post_trade(
    *,
    action: str,
    symbol: Optional[str] = None,
    qty: float = 0.0,
    price: float = 0.0,
    fee: float = 0.0,
    trade_id: str,
    ts_utc: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convenience router if your sync emits normalized actions.
    Supported actions (case-insensitive):
      BUY, SELL, SHORT_OPEN (SELL_SHORT, SELL_TO_OPEN), SHORT_COVER (BUY_TO_COVER),
      DIVIDEND (DIV), INTEREST (INT), DEPOSIT (TRANSFER_IN), WITHDRAWAL (TRANSFER_OUT), FEE (COMMISSION)
    """
    a = (action or "").strip().upper()

    # Trades
    if a in ("BUY", "LONG", "BUY_TO_OPEN"):
        assert symbol is not None
        return post_buy(symbol=symbol, qty=qty, price=price, fee=fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)
    if a in ("SELL", "SELL_TO_CLOSE"):
        assert symbol is not None
        return post_sell(symbol=symbol, qty=qty, price=price, fee=fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)
    if a in ("SHORT_OPEN", "SELL_SHORT", "SELL_TO_OPEN"):
        assert symbol is not None
        return post_short_open(symbol=symbol, qty=qty, price=price, fee=fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)
    if a in ("SHORT_COVER", "BUY_TO_COVER"):
        assert symbol is not None
        return post_short_cover(symbol=symbol, qty=qty, price=price, fee=fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)

    # Cash/admin
    if a in ("DIVIDEND", "DIV"):
        return post_dividend(amount=qty or price or fee, trade_id=trade_id, symbol=symbol, ts_utc=ts_utc, meta=meta)
    if a in ("INTEREST", "INT"):
        return post_interest(amount=qty or price or fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)
    if a in ("DEPOSIT", "TRANSFER_IN"):
        return post_deposit(amount=qty or price or fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)
    if a in ("WITHDRAWAL", "TRANSFER_OUT"):
        return post_withdrawal(amount=qty or price or fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)
    if a in ("FEE", "COMMISSION"):
        return post_fee(amount=qty or price or fee, trade_id=trade_id, ts_utc=ts_utc, meta=meta)

    raise ValueError(f"Unsupported action '{action}'")
