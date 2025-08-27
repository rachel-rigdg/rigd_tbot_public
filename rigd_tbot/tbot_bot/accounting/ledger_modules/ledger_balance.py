# tbot_bot/accounting/ledger_modules/ledger_balance.py

"""
Balance and running balance computation helpers for the ledger.

Requirements addressed (v048):
- Include opening balance (OB) legs in rollups.
- Date/range filters default to include OB on fresh ledgers.
- Provide section totals (Assets/Liabilities/Equity) and selected account subtotals for /ledger/balances.
- Preserve legacy calculate_account_balances() return shape for backward compatibility.
"""

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
# DB helpers
# ---------------------------------------------------------------------------

def _open_db() -> sqlite3.Connection:
    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ob_clause(column_group_id: str = "group_id") -> str:
    """SQL snippet to include Opening Balance groups regardless of date filter."""
    # OB groups are posted as "OPENING_BALANCE_YYYYMMDD"
    return f"{column_group_id} LIKE 'OPENING_BALANCE_%'"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_account_balances() -> Dict[str, float]:
    """
    Legacy/simple summary:
      Computes SUM(total_value) grouped by account from the trades table.
      Includes Opening Balance legs implicitly (no date filter).
    Returns:
      {account_code: balance_float}
    """
    if TEST_MODE_FLAG.exists():
        return {}
    with _open_db() as conn:
        cur = conn.execute(
            "SELECT account, COALESCE(SUM(total_value),0.0) AS balance "
            "FROM trades GROUP BY account"
        )
        return {row["account"]: float(row["balance"] or 0.0) for row in cur.fetchall() if row["account"]}


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
      - OB groups (group_id LIKE 'OPENING_BALANCE_%') are ALWAYS included regardless of date filters.
      - Section totals computed for Assets, Liabilities, Equity (based on COA root).
      - Returns by-account subtotals for 'selected_accounts' if provided; otherwise returns all non-zero accounts.

    Returns:
      {
        "as_of_utc": "...Z",
        "totals": { "assets": "0.00", "liabilities": "0.00", "equity": "0.00" },
        "by_account": [
          { "account_code": "1030", "name": "Cash — Broker", "balance": "123.45" },
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
    df_clause = ""
    params: List[object] = []
    if date_from_utc:
        # inclusive lower bound
        df_clause += " AND (datetime_utc >= ? OR " + _ob_clause() + ")"
        params.append(date_from_utc)
    if date_to_utc:
        # inclusive upper bound (sqlite <= works for both date & datetime strings)
        df_clause += " AND (datetime_utc <= ? OR " + _ob_clause() + ")"
        params.append(date_to_utc)

    # Group balances by account, including OB regardless of date filters
    sql = (
        "SELECT account AS account_code, COALESCE(SUM(total_value),0.0) AS balance "
        "FROM trades "
        "WHERE 1=1 "
        f"{df_clause} "
        "GROUP BY account "
        "HAVING account IS NOT NULL AND account <> ''"
    )

    by_acct_rows: List[dict] = []
    with _open_db() as conn:
        cur = conn.execute(sql, tuple(params))
        for row in cur.fetchall():
            code = str(row["account_code"])
            bal = float(row["balance"] or 0.0)
            if selected_accounts is not None and len(selected_accounts) > 0:
                if code not in set(selected_accounts):
                    # skip non-selected accounts
                    continue
            # include all non-zero or explicitly selected
            if bal != 0.0 or (selected_accounts and code in selected_accounts):
                by_acct_rows.append(
                    {
                        "account_code": code,
                        "name": code_to_name.get(code, ""),
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
