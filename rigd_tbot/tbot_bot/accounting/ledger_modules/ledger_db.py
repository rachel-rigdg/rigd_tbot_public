# tbot_bot/accounting/ledger_modules/ledger_db.py

"""
Ledger DB helpers (v048)
- Resolve DB path via path_resolver + utils_identity (no inline decrypts).
- Provide migrations runner.
- Use pragma-configured connections via ledger_core (busy_timeout, WAL, foreign_keys=ON).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Set, Tuple, List

from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_schema_path
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_core import get_conn, tx_context

# ---- Compliance (v048 preferred) ----
try:
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import validate_entries as _validate_entries  # type: ignore
    def _is_compliant(entry: dict) -> bool:
        ok, _ = _validate_entries([entry])
        return bool(ok)
except Exception:
    try:
        from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import is_compliant_ledger_entry as _legacy_is_compliant  # type: ignore
        def _is_compliant(entry: dict) -> bool:
            return bool(_legacy_is_compliant(entry))
    except Exception:
        def _is_compliant(entry: dict) -> bool:  # type: ignore
            return True  # last-resort permissive (should not happen in prod)


CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"


def _identity_tuple() -> tuple[str, str, str, str]:
    """
    (entity_code, jurisdiction_code, broker_code, bot_id) from BOT identity.
    """
    parts = str(get_bot_identity()).split("_")
    if len(parts) < 4:
        raise ValueError("Invalid BOT identity; expected 'ENTITY_JURISDICTION_BROKER_BOTID'")
    return parts[0], parts[1], parts[2], parts[3]


def get_db_path() -> str:
    """
    Resolved ledger DB path for current identity (compat helper).
    """
    ec, jc, bc, bid = _identity_tuple()
    return str(resolve_ledger_db_path(ec, jc, bc, bid))


def _get_table_columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    """
    Return set of column names for a given table using PRAGMA table_info.
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def validate_ledger_schema(db_path: Optional[str] = None, schema_path: Optional[str] = None) -> bool:
    """
    Validates the ledger DB with three gates (in order):
      1) PRAGMA integrity_check → must return only 'ok'
      2) Required columns exist in trades:
         {'datetime_utc','timestamp_utc','trade_id','group_id','side','amount','total_value','fitid','created_at_utc'}
      3) EXPLAIN pass across reference schema statements (syntax for explainable statements only)
    Returns True if all checks pass, else False.
    """
    try:
        dsn = db_path or get_db_path()
        schema_file = schema_path or resolve_ledger_schema_path()
        with open(schema_file, "r", encoding="utf-8") as f:
            schema = f.read()

        with get_conn() as conn:
            # 1) Corruption/integrity check
            ic_rows = conn.execute("PRAGMA integrity_check").fetchall()
            if not ic_rows or any(str(row[0]).lower() != "ok" for row in ic_rows):
                return False

            # 2) Required columns in trades
            required = {
                "datetime_utc",
                "timestamp_utc",
                "trade_id",
                "group_id",
                "side",
                "amount",
                "total_value",
                "fitid",
                "created_at_utc",
            }
            cols = _get_table_columns(conn, "trades")
            if not required.issubset(cols):
                return False

            # 3) Secondary EXPLAIN pass: only for statements SQLite can EXPLAIN
            cursor = conn.cursor()
            for raw in schema.split(";"):
                stmt = raw.strip()
                if not stmt:
                    continue
                # Skip comments/PRAGMAs/DDL and other non-explainable statements
                leading = stmt.split(None, 1)[0].upper() if stmt.split() else ""
                if not leading or leading.startswith("--") or leading in {
                    "PRAGMA", "CREATE", "ALTER", "DROP", "VACUUM",
                    "BEGIN", "COMMIT", "END",
                }:
                    continue
                # Attempt EXPLAIN for DML-like statements only
                try:
                    cursor.execute(f"EXPLAIN {stmt}")
                except sqlite3.DatabaseError:
                    return False

        return True
    except Exception:
        return False


def _map_action(action: str | None) -> str:
    if not action or not isinstance(action, str):
        return "other"
    a = action.lower()
    if a in ("buy", "long"):
        return "long"
    if a in ("sell", "short"):
        return "short"
    if a in ("put", "call", "assignment", "exercise", "expire", "reorg", "inverse"):
        return a
    return "other"


def _sanitize_for_sqlite(entry: dict) -> dict:
    """
    Fill required fields, set identity defaults, compute amount/side defaults,
    and JSON-encode complex objects to avoid sqlite binding errors.
    """
    e = dict(entry)

    # Identity fields (NOT NULL in schema)
    ec, jc, bc, bid = _identity_tuple()
    e.setdefault("entity_code", ec)
    e.setdefault("jurisdiction_code", jc)
    e.setdefault("broker_code", bc)
    e.setdefault("bot_id", bid)

    # Ensure trade_id / group_id
    if not e.get("trade_id"):
        e["trade_id"] = f"{bc}_{bid}_{hash(frozenset(e.items()))}"
    if not e.get("group_id"):
        e["group_id"] = e.get("trade_id")

    # Defaults for required numeric/side fields
    if "total_value" not in e or e["total_value"] is None:
        e["total_value"] = 0.0

    # Side default
    if not e.get("side"):
        e["side"] = "debit"

    # Amount sign based on side if missing
    if "amount" not in e or e["amount"] is None:
        try:
            val = float(e.get("total_value", 0.0))
        except Exception:
            val = 0.0
        e["amount"] = -abs(val) if str(e.get("side", "")).lower() == "credit" else abs(val)

    # Commission/Fee defaults
    if e.get("commission") is None:
        e["commission"] = 0.0
    if e.get("fee") is None:
        e["fee"] = 0.0

    # Account default (schema marks NOT NULL)
    if not e.get("account"):
        e["account"] = "Uncategorized:Credit" if e["side"].lower() == "credit" else "Uncategorized:Debit"

    # Normalize action/status
    e["action"] = _map_action(e.get("action"))
    if not e.get("status"):
        e["status"] = "ok"

    # Fill any missing schema fields (ensure key exists)
    for k in TRADES_FIELDS:
        if k not in e:
            e[k] = None

    # JSON-encode complex objects for safe sqlite binding
    for k, v in list(e.items()):
        if isinstance(v, (dict, list)):
            e[k] = json.dumps(v, default=str)

    return e


def add_entry(entry: dict) -> None:
    """
    Adds a single ledger entry to the trades table.
    Enforces compliance and sanitization to prevent invalid rows.
    """
    if not isinstance(entry, dict):
        raise RuntimeError("Entry must be a dict")

    if not _is_compliant(entry):
        return  # ignore non-compliant entries (already audited by compliance module)

    e = _sanitize_for_sqlite(entry)

    keys = ", ".join(TRADES_FIELDS)
    placeholders = ", ".join("?" for _ in TRADES_FIELDS)
    values = tuple(e.get(k) for k in TRADES_FIELDS)

    with tx_context() as conn:
        conn.execute(f"INSERT INTO trades ({keys}) VALUES ({placeholders})", values)


def _schema_has_amount_side() -> bool:
    """
    Checks if the trades table has 'amount' and 'side' columns.
    """
    try:
        with get_conn() as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()]
            return ("amount" in cols) and ("side" in cols)
    except Exception:
        return False


def post_double_entry(entries: Iterable[dict], mapping_table: Optional[dict] = None):
    """
    Posts balanced double-entry records using the double-entry helper module.
    Applies compliance to each raw entry before delegating.
    """
    from tbot_bot.accounting.ledger_modules.ledger_double_entry import (  # local import to avoid cycles
        post_double_entry as _post_double_entry_helper,
    )

    # Filter non-compliant
    filtered = [e for e in entries if isinstance(e, dict) and _is_compliant(e)]
    if not filtered:
        return []

    return _post_double_entry_helper(filtered, mapping_table)


def run_schema_migration(migration_sql_path: str) -> None:
    """
    Runs a single schema migration SQL script on the ledger DB (atomic).
    """
    with open(migration_sql_path, "r", encoding="utf-8") as f:
        migration_sql = f.read()
    with tx_context() as conn:
        conn.executescript(migration_sql)


def run_migrations_dir(migrations_dir: str) -> None:
    """
    Runs all *.sql migrations in a directory in lexical order.
    """
    p = Path(migrations_dir)
    files = sorted([f for f in p.iterdir() if f.suffix.lower() == ".sql"])
    for f in files:
        run_schema_migration(str(f))


def reconcile_ledger_with_coa() -> bool:
    """
    Placeholder for reconciliation logic between ledger entries and COA accounts.
    """
    try:
        with get_conn():
            pass
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to reconcile ledger with COA: {e}")
