# tbot_bot/accounting/ledger_modules/ledger_opening_balance.py
"""
Opening Balance (OB) posting helper.

post_opening_balances_if_needed(sync_run_id, broker_snapshot):
  • Detect empty ledger; construct OB group_id = "OPENING_BALANCE_YYYYMMDD".
  • Create balanced legs:
      - Cash:   (Debit)  Assets:Brokerage:Cash
                (Credit) Equity:OpeningBalances
      - Positions (per symbol):
                (Debit)  Assets:Brokerage:Equity:{SYMBOL} @ basis (or MV flagged as est)
                (Credit) Equity:OpeningBalances
  • Mark opening_balances_posted=true in meta; emit full audit entry; single atomic batch.

Notes:
  - No hardcoded paths: COA account codes resolved from COA tree via name-path matching.
  - UTC timestamps; append-only audit via ledger_audit.append.
  - Double-entry compliance (sum of legs == 0).
  - Entity/jurisdiction scoped via resolve_ledger_db_path.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import (
    resolve_ledger_db_path,
    resolve_coa_json_path,
)
from tbot_bot.accounting.ledger_modules.ledger_audit import append as audit_append  # immutable JSONL


# -------------------------
# COA lookups (by name-path)
# -------------------------

def _load_coa_tree() -> List[dict]:
    import json
    p = resolve_coa_json_path()
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "accounts" in data:
        return data["accounts"] or []
    return data if isinstance(data, list) else []


def _find_code_by_name_path(names: List[str]) -> Optional[str]:
    """
    Find an account code by a list of human-readable names representing a path,
    e.g. ["Assets", "Brokerage", "Cash"].
    Case-insensitive name match; returns first matching account code.
    """
    tree = _load_coa_tree()

    def norm(s: str) -> str:
        return (s or "").strip().lower()

    def walk(nodes: List[dict], path_names: List[str], depth: int) -> List[dict]:
        if depth >= len(path_names):
            return []
        target = norm(path_names[depth])
        out = []
        for n in nodes or []:
            if norm(n.get("name", "")) == target:
                if depth == len(path_names) - 1:
                    if n.get("active", True):
                        code = n.get("code")
                        if code:
                            return [{"code": code}]
                else:
                    kids = n.get("children") or []
                    out = walk(kids, path_names, depth + 1)
                    if out:
                        return out
        return out

    hit = walk(tree, names, 0)
    return hit[0]["code"] if hit else None


def _find_or_fallback_symbol_equity_code(symbol: str) -> Optional[str]:
    """
    Try exact path ["Assets","Brokerage","Equity", <SYMBOL>]; if not found,
    fall back to ["Assets","Brokerage","Equity"] (aggregate). Returns account code or None.
    """
    cand = _find_code_by_name_path(["Assets", "Brokerage", "Equity", symbol])
    if cand:
        return cand
    return _find_code_by_name_path(["Assets", "Brokerage", "Equity"])


def _resolve_required_codes() -> Dict[str, Optional[str]]:
    """
    Resolve commonly used OB accounts by name-path. Returns:
      { "cash": code_or_None, "eq_opening": code_or_None }
    """
    return {
        "cash": _find_code_by_name_path(["Assets", "Brokerage", "Cash"]),
        "eq_opening": _find_code_by_name_path(["Equity", "OpeningBalances"]),
    }


# -------------------------
# DB helpers
# -------------------------

def _open_db() -> sqlite3.Connection:
    e, j, b, bot_id = load_bot_identity().split("_")
    db_path = resolve_ledger_db_path(e, j, b, bot_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_has(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [r["name"] for r in cur.fetchall()]


def _insert_trade(conn: sqlite3.Connection, values: Dict[str, Any]) -> None:
    """
    Insert a row into trades with only the columns that exist.
    """
    cols = set(_columns(conn, "trades"))
    data = {k: v for k, v in values.items() if k in cols}
    keys = ",".join(data.keys())
    qs = ",".join(["?"] * len(data))
    conn.execute(f"INSERT INTO trades ({keys}) VALUES ({qs})", tuple(data.values()))


def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    if not _table_has(conn, "meta"):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )


def _meta_get(conn: sqlite3.Connection, key: str) -> Optional[str]:
    _ensure_meta_table(conn)
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn: sqlite3.Connection, key: str, val: str) -> None:
    _ensure_meta_table(conn)
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, val),
    )


# -------------------------
# Core
# -------------------------

def _yyyymmdd_from_snapshot(snapshot: Dict[str, Any]) -> str:
    # prefer provided as_of_utc; else today (UTC)
    asof = snapshot.get("as_of_utc") if isinstance(snapshot, dict) else None
    try:
        if asof:
            # Accept YYYY-MM-DD or full ISO
            date_part = str(asof).split("T")[0]
            return date_part.replace("-", "")
    except Exception:
        pass
    now = datetime.utcnow()
    return now.strftime("%Y%m%d")


def post_opening_balances_if_needed(sync_run_id: str, broker_snapshot: Dict[str, Any]) -> bool:
    """
    Detect empty ledger and post opening balances as a single atomic batch.

    Args:
      sync_run_id: identifier of the current sync run (included in audit).
      broker_snapshot: {
         "as_of_utc": "...",
         "cash": 123.45,
         "positions": [
             {"symbol":"AAPL","quantity":10,"basis":1500.0,"market_value":1900.0},
             ...
         ]
      }

    Returns:
      True if OB were posted in this invocation, else False.
    """
    # Feature guard by convention: only when ledger empty AND not previously posted.
    ts_utc = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    group_suffix = _yyyymmdd_from_snapshot(broker_snapshot)
    group_id = f"OPENING_BALANCE_{group_suffix}"

    codes = _resolve_required_codes()
    cash_code = codes.get("cash")
    eq_opening_code = codes.get("eq_opening")

    with _open_db() as conn:
        conn.execute("BEGIN")
        try:
            # Early exits
            posted_flag = _meta_get(conn, "opening_balances_posted")
            if posted_flag == "true":
                conn.rollback()
                return False

            rowcount = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
            if rowcount and rowcount > 0:
                _meta_set(conn, "opening_balances_posted", "true")  # protect future runs
                conn.commit()
                return False

            # Optional trade_groups row
            if _table_has(conn, "trade_groups"):
                cols_g = set(_columns(conn, "trade_groups"))
                group_values = {
                    "group_id": group_id,
                    "datetime_utc": broker_snapshot.get("as_of_utc") or ts_utc,
                    "type": "OPENING_BALANCE",
                    "status": "posted",
                    "sync_run_id": sync_run_id,
                    "notes": "Auto-posted opening balances",
                }
                gdata = {k: v for k, v in group_values.items() if k in cols_g}
                if gdata:
                    keys = ",".join(gdata.keys())
                    qs = ",".join(["?"] * len(gdata))
                    conn.execute(f"INSERT INTO trade_groups ({keys}) VALUES ({qs})", tuple(gdata.values()))

            # Build legs
            legs: List[Dict[str, Any]] = []
            cash_amt = float(broker_snapshot.get("cash") or 0.0)
            if cash_amt != 0.0:
                if not cash_code or not eq_opening_code:
                    raise ValueError("Required COA accounts for Opening Balance (Cash/Equity:OpeningBalances) not found.")
                # Debit cash (positive), Credit opening equity (negative)
                legs.append({
                    "group_id": group_id,
                    "datetime_utc": broker_snapshot.get("as_of_utc") or ts_utc,
                    "account": cash_code,
                    "total_value": round(cash_amt, 2),
                    "action": "ob_post",
                    "strategy": "open",
                    "tags": "opening_balance,cash",
                    "notes": "Opening cash",
                    "status": "ok",
                    "sync_run_id": sync_run_id,
                })
                legs.append({
                    "group_id": group_id,
                    "datetime_utc": broker_snapshot.get("as_of_utc") or ts_utc,
                    "account": eq_opening_code,
                    "total_value": round(-cash_amt, 2),
                    "action": "ob_post",
                    "strategy": "open",
                    "tags": "opening_balance,equity",
                    "notes": "Opening equity offset (cash)",
                    "status": "ok",
                    "sync_run_id": sync_run_id,
                })

            # Positions
            pos_list = broker_snapshot.get("positions") or []
            for p in pos_list:
                symbol = str(p.get("symbol") or "").strip()
                qty = float(p.get("quantity") or 0.0)
                basis = p.get("basis")
                mv = p.get("market_value")
                # value to post: prefer basis; else market value with "est" note
                use_mv = False
                if basis is None:
                    if mv is None:
                        continue  # skip unknown valuation
                    value = float(mv or 0.0)
                    use_mv = True
                else:
                    value = float(basis or 0.0)
                if value == 0.0:
                    continue

                acct_equity_symbol = _find_or_fallback_symbol_equity_code(symbol or "UNSPEC")
                if not acct_equity_symbol or not eq_opening_code:
                    raise ValueError(f"Required COA account(s) for position {symbol} not found.")

                note_suffix = " (est @ MV)" if use_mv else " (@ basis)"
                # Debit position asset, Credit opening equity offset
                legs.append({
                    "group_id": group_id,
                    "datetime_utc": broker_snapshot.get("as_of_utc") or ts_utc,
                    "account": acct_equity_symbol,
                    "symbol": symbol or None,
                    "quantity": qty if qty else None,
                    "total_value": round(value, 2),
                    "action": "ob_post",
                    "strategy": "open",
                    "tags": f"opening_balance,position,{symbol}" if symbol else "opening_balance,position",
                    "notes": f"Opening position {symbol}{note_suffix}".strip(),
                    "status": "ok",
                    "sync_run_id": sync_run_id,
                })
                legs.append({
                    "group_id": group_id,
                    "datetime_utc": broker_snapshot.get("as_of_utc") or ts_utc,
                    "account": eq_opening_code,
                    "symbol": symbol or None,
                    "total_value": round(-value, 2),
                    "action": "ob_post",
                    "strategy": "open",
                    "tags": "opening_balance,equity",
                    "notes": f"Opening equity offset ({symbol})".strip(),
                    "status": "ok",
                    "sync_run_id": sync_run_id,
                })

            # Validate zero-sum
            total = sum(float(l["total_value"]) for l in legs)
            if round(total, 2) != 0.0:
                raise ValueError(f"Opening balance legs not balanced (sum={total:.2f})")

            # Insert legs
            for leg in legs:
                _insert_trade(conn, leg)

            # Mark meta + commit
            _meta_set(conn, "opening_balances_posted", "true")
            conn.commit()

            # Structured audit
            e, j, b, bot_id = load_bot_identity().split("_")
            audit_append(
                event="opening_balance_posted",
                ts_utc=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
                sync_run_id=sync_run_id,
                group_id=group_id,
                broker_code=b,
                entity_code=e,
                jurisdiction_code=j,
                legs_count=len(legs),
                cash_posted=cash_amt,
                positions_count=len(pos_list),
            )

            return True

        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
