# tbot_bot/accounting/ledger_modules/ledger_balance.py

"""
Balance and running balance computation helpers for the ledger.

Requirements addressed (v048+):
- Include opening balance (OB) legs in rollups.
- Date/range filters default to include OB on fresh ledgers.
- Provide section totals (Assets/Liabilities/Equity) and selected account subtotals for /ledger/balances.
- Explicit breakdowns:
    * Assets:Brokerage:Cash
    * Assets:Brokerage:Equity:{SYMBOL}  (longs per symbol)
    * Liabilities:Short Positions:{SYMBOL}  (shorts per symbol; liability increases with credits)
- Treat account 4010 as P&L (exclude from cash/positions breakdown).
- Preserve legacy calculate_account_balances() return shape for backward compatibility.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_entry import load_internal_ledger
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import (
    resolve_ledger_db_path,
    resolve_coa_json_path,
)

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

# ---------------------------------------------------------------------------
# COA helpers (local, read-only; paths resolved via path_resolver)
# ---------------------------------------------------------------------------

def _load_coa_tree() -> List[dict]:
    """
    Loads COA JSON (structure-only). Supports both bare list or {"accounts":[...]} layouts.
    """
    try:
        coa_path = resolve_coa_json_path()
        with open(coa_path, "r", encoding="utf-8") as f:
            data = __import__("json").load(f)
        if isinstance(data, dict) and "accounts" in data:
            return data["accounts"] or []
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _build_coa_indexes() -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Returns:
      - code_to_name: {account_code -> account_name}
      - code_to_root: {account_code -> top-level root name ('Assets'|'Liabilities'|'Equity'|...)}
    """
    tree = _load_coa_tree()
    code_to_name: Dict[str, str] = {}
    code_to_root: Dict[str, str] = {}

    def walk(nodes: List[dict], root_name: Optional[str] = None):
        for n in nodes or []:
            code = str(n.get("code", "")).strip()
            name = str(n.get("name", "")).strip()
            if not root_name:
                root = name  # first level node (e.g., "Assets")
            else:
                root = root_name
            if code:
                code_to_name[code] = name
                code_to_root[code] = root
            children = n.get("children") or []
            if children:
                walk(children, root)
    walk(tree, None)
    return code_to_name, code_to_root


# ---------------------------------------------------------------------------
# Account classifiers / parsing
# ---------------------------------------------------------------------------

def _acct_is_broker_cash(code: str) -> bool:
    c = (code or "").strip()
    return c == "Assets:Brokerage:Cash" or c.startswith("Assets:Brokerage:Cash:")

def _acct_equity_symbol(code: str) -> Optional[str]:
    """
    Returns SYMBOL for 'Assets:Brokerage:Equity:{SYMBOL}' else None.
    """
    c = (code or "").strip()
    prefix = "Assets:Brokerage:Equity:"
    if c.startswith(prefix) and len(c) > len(prefix):
        return c[len(prefix):]
    return None

def _acct_short_symbol(code: str) -> Optional[str]:
    """
    Returns SYMBOL for 'Liabilities:Short Positions:{SYMBOL}' else None.
    """
    c = (code or "").strip()
    prefix = "Liabilities:Short Positions:"
    if c.startswith(prefix) and len(c) > len(prefix):
        return c[len(prefix):]
    return None

def _is_4010_pnl(code: str, name: str) -> bool:
    """
    Treat account '4010' as P&L and exclude it from cash/positions breakdown.
    We consider common variants conservatively.
    """
    c = (code or "").strip()
    n = (name or "").strip().lower()
    if c == "4010" or c.endswith(":4010"):
        return True
    # If COA uses names only, treat obvious realized gain buckets as P&L
    if "realized" in n and ("gain" in n or "loss" in n):
        return True
    return False


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _open_db() -> sqlite3.Connection:
    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    # Concurrency-friendly connection
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    except Exception:
        pass
    return conn


def _is_opening_balance_sql(prefix: str = "") -> str:
    """
    Predicate to identify opening-balance legs regardless of how they were seeded.
    Matches any of:
      - action = 'OPENING_BALANCE'
      - tags LIKE '%opening_balance%'
      - group_id LIKE 'OB-%' (journal-grouped opening seed)
      - group_id LIKE 'OPENING_BALANCE%' (legacy)
    Optional `prefix` allows qualifying column names with a table alias.
    """
    dot = f"{prefix}." if prefix else ""
    return (
        f"( {dot}action = 'OPENING_BALANCE' "
        f"OR COALESCE({dot}tags,'') LIKE '%opening_balance%' "
        f"OR COALESCE({dot}group_id,'') LIKE 'OB-%' "
        f"OR COALESCE({dot}group_id,'') LIKE 'OPENING_BALANCE%' )"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_account_balances(include_opening: bool = False) -> Dict[str, object]:
    """
    Backward-compatible summary with optional rich payload.

    Legacy (no-arg / include_opening=False):
      Returns a simple mapping of balances by account:
        {account_code: balance_float}

    New (include_opening=True):
      Returns a structured payload used by the web UI:
        {
          "as_of_utc": "...Z",
          "totals": { "assets": "0.00", "liabilities": "0.00", "equity": "0.00" },
          "by_account": [
            { "account_code": "...", "name": "...", "balance": "..." },
            ...
          ],
          "running_balance": "123.45",
          "breakdown": {
              "cash_brokerage": "123.45",
              "long_equity_by_symbol": {"AAPL": "100.00", ...},
              "short_positions_by_symbol": {"TSLA": "50.00", ...}  # positive = liability magnitude
          }
        }

      Notes:
        - OB (opening balance) legs are included.
        - P&L (e.g., 4010 Realized Gains) is EXCLUDED from the cash/positions breakdown.
        - Section totals derive from COA roots.
    """
    # --- Test mode short-circuit ---
    if TEST_MODE_FLAG.exists():
        if not include_opening:
            return {}
        return {
            "as_of_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "totals": {"assets": "0.00", "liabilities": "0.00", "equity": "0.00"},
            "by_account": [],
            "running_balance": "0.00",
            "breakdown": {
                "cash_brokerage": "0.00",
                "long_equity_by_symbol": {},
                "short_positions_by_symbol": {},
            },
        }

    if not include_opening:
        # ---- Legacy shape ----
        with _open_db() as conn:
            cur = conn.execute(
                "SELECT account, COALESCE(SUM(total_value),0.0) AS balance "
                "FROM trades GROUP BY account"
            )
            return {row["account"]: float(row["balance"] or 0.0) for row in cur.fetchall() if row["account"]}

    # ---- Rich payload for UI (include OB) ----
    code_to_name, code_to_root = _build_coa_indexes()

    # by-account balances (including OB)
    by_acct_rows: List[dict] = []
    with _open_db() as conn:
        cur = conn.execute(
            "SELECT account AS account_code, COALESCE(SUM(total_value),0.0) AS balance "
            "FROM trades "
            "WHERE account IS NOT NULL AND account <> '' "
            "GROUP BY account"
        )
        raw_by_acct = [(str(r["account_code"]), float(r["balance"] or 0.0)) for r in cur.fetchall()]

        # Build rows and also compute specialized breakdowns
        cash_total = 0.0
        long_equity: Dict[str, float] = {}
        short_positions: Dict[str, float] = {}

        for code, bal in raw_by_acct:
            name = code_to_name.get(code, "")

            # Populate the table payload
            by_acct_rows.append(
                {
                    "account_code": code,
                    "name": name,
                    "balance": f"{bal:.2f}",
                }
            )

            # Skip P&L 4010 from breakdowns
            if _is_4010_pnl(code, name):
                continue

            # Cash (brokerage)
            if _acct_is_broker_cash(code):
                cash_total += bal
                continue

            # Long equity by symbol (asset balances are positive when debited)
            sym_long = _acct_equity_symbol(code)
            if sym_long:
                long_equity[sym_long] = round(long_equity.get(sym_long, 0.0) + bal, 2)
                continue

            # Short positions by symbol
            sym_short = _acct_short_symbol(code)
            if sym_short:
                # Liability increases with credits (negative ledger sum). Report positive magnitude.
                magnitude = -bal  # so credits (negative) => positive number
                short_positions[sym_short] = round(short_positions.get(sym_short, 0.0) + magnitude, 2)
                continue

        # running balance = sum of all total_value (including OB)
        running_row = conn.execute(
            "SELECT COALESCE(SUM(total_value),0.0) FROM trades"
        ).fetchone()
        running_total = float(running_row[0] or 0.0)

    # section totals via COA root (Assets/Liabilities/Equity)
    assets = liabilities = equity = 0.0
    for r in by_acct_rows:
        root = code_to_root.get(r["account_code"], "")
        bal = float(r["balance"])
        if root.lower().startswith("asset"):
            assets += bal
        elif root.lower().startswith("liabil"):
            liabilities += bal
        elif root.lower().startswith("equity"):
            equity += bal

    return {
        "as_of_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "totals": {
            "assets": f"{assets:.2f}",
            "liabilities": f"{liabilities:.2f}",
            "equity": f"{equity:.2f}",
        },
        "by_account": by_acct_rows,
        "running_balance": f"{running_total:.2f}",
        "breakdown": {
            "cash_brokerage": f"{cash_total:.2f}",
            "long_equity_by_symbol": {k: f"{v:.2f}" for k, v in sorted(long_equity.items()) if abs(v) > 0.00001},
            "short_positions_by_symbol": {k: f"{v:.2f}" for k, v in sorted(short_positions.items()) if abs(v) > 0.00001},
        },
    }


def calculate_running_balances() -> List[dict]:
    """
    Returns list of dicts: each ledger entry with added field 'running_balance'.
    Sorted by datetime_utc asc, id tiebreaker.
    OB legs (if any) are inherently included by load_internal_ledger().
    """
    if TEST_MODE_FLAG.exists():
        return []
    entries = load_internal_ledger()

    # Ensure all TRADES_FIELDS present
    for entry in entries:
        for k in TRADES_FIELDS:
            if k not in entry:
                entry[k] = None

    # Sort by datetime then id
    entries.sort(key=lambda e: (e.get("datetime_utc", "") or "", e.get("id", 0) or 0))

    running = 0.0
    out: List[dict] = []
    for entry in entries:
        val = float(entry.get("total_value") or 0.0)
        running += val
        entry["running_balance"] = round(running, 2)
        out.append(entry)
    return out


def balances_panel(
    date_from_utc: Optional[str] = None,
    date_to_utc: Optional[str] = None,
    selected_accounts: Optional[List[str]] = None,
) -> Dict[str, object]:
    """
    Structured balances for /ledger/balances endpoint.

    Args:
      date_from_utc: ISO date or datetime (UTC). Inclusive (>=).
      date_to_utc:   ISO date or datetime (UTC). Inclusive (<=) on day; if datetime, uses <= exact.
      selected_accounts: optional list of account codes to include as explicit subtotals.

    Behavior:
      - OB legs are ALWAYS included regardless of date filters (identified via action/tags/group_id patterns).
      - Section totals computed for Assets, Liabilities, Equity (based on COA root).
      - Returns by-account subtotals for 'selected_accounts' if provided; otherwise returns all non-zero accounts.
      - Cash / positions and shorts can be derived client-side by applying the same classifiers as above.

    Returns:
      {
        "as_of_utc": "...Z",
        "totals": { "assets": "0.00", "liabilities": "0.00", "equity": "0.00" },
        "by_account": [
          { "account_code": "...", "name": "...", "balance": "..." },
          ...
        ]
      }
    """
    if TEST_MODE_FLAG.exists():
        return {
            "as_of_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "totals": {"assets": "0.00", "liabilities": "0.00", "equity": "0.00"},
            "by_account": [],
        }

    code_to_name, code_to_root = _build_coa_indexes()

    # Normalize date filters (treat YYYY-MM-DD as whole-day bounds)
    df_clauses: List[str] = []
    params: List[object] = []

    if date_from_utc:
        # inclusive lower bound OR opening-balance
        df_clauses.append(f"(datetime_utc >= ? OR {_is_opening_balance_sql()})")
        params.append(date_from_utc)
    if date_to_utc:
        # inclusive upper bound OR opening-balance
        df_clauses.append(f"(datetime_utc <= ? OR {_is_opening_balance_sql()})")
        params.append(date_to_utc)

    where_clause = "WHERE 1=1 "
    if df_clauses:
        where_clause += " AND " + " AND ".join(df_clauses)

    # Group balances by account, including OB regardless of the provided date filters
    sql = (
        "SELECT account AS account_code, COALESCE(SUM(total_value),0.0) AS balance "
        "FROM trades "
        f"{where_clause} "
        "GROUP BY account "
        "HAVING account IS NOT NULL AND account <> ''"
    )

    by_acct_rows: List[dict] = []
    with _open_db() as conn:
        cur = conn.execute(sql, tuple(params))
        for row in cur.fetchall():
            code = str(row["account_code"])
            bal = float(row["balance"] or 0.0)
            name = code_to_name.get(code, "")
            # include all non-zero or explicitly selected
            if selected_accounts is not None and len(selected_accounts) > 0 and code not in set(selected_accounts):
                continue
            if bal != 0.0 or (selected_accounts and code in selected_accounts):
                by_acct_rows.append(
                    {
                        "account_code": code,
                        "name": name,
                        "balance": f"{bal:.2f}",
                    }
                )

    # Section totals using COA root mapping; unknown roots ignored for section rollups
    assets = liabilities = equity = 0.0
    for r in by_acct_rows:
        root = code_to_root.get(r["account_code"], "")
        bal = float(r["balance"])
        if root.lower().startswith("asset"):
            assets += bal
        elif root.lower().startswith("liabil"):
            liabilities += bal
        elif root.lower().startswith("equity"):
            equity += bal

    result = {
        "as_of_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "totals": {
            "assets": f"{assets:.2f}",
            "liabilities": f"{liabilities:.2f}",
            "equity": f"{equity:.2f}",
        },
        "by_account": by_acct_rows,
    }
    return result
