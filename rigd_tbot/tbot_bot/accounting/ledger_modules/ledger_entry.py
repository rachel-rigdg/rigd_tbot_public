# tbot_bot/accounting/ledger_modules/ledger_entry.py

"""
Legacy single-entry ledger helpers.
All new posting/editing/deleting must use double-entry and helpers in ledger_double_entry.py / ledger_edit.py.
"""

import sqlite3
import json
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_web.support.auth_web import get_current_user
from tbot_bot.accounting.ledger_modules.ledger_account_map import load_broker_code, load_account_number
from tbot_bot.accounting.ledger_modules.ledger_edit import edit_ledger_entry, delete_ledger_entry  # Use shared helpers
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import compliance_filter_entry


def get_identity_tuple():
    identity = load_bot_identity()
    parts = identity.split("_") if identity else []
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])


def _resolve_db_path() -> str:
    entity, juris, broker, bot_id = get_identity_tuple()
    return resolve_ledger_db_path(entity, juris, broker, bot_id)


def _table_has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        return col in cols
    except Exception:
        return False


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
            ).fetchone()
        )
    except Exception:
        return False


def load_internal_ledger():
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query = "SELECT id, " + ", ".join(TRADES_FIELDS) + " FROM trades"
    cursor = conn.execute(query)
    results = []
    for row in cursor.fetchall():
        d = {k: row[k] for k in row.keys()}
        results.append(d)
    conn.close()
    return results


def mark_entry_resolved(entry_id):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    current_user = get_current_user()
    updater = (
        current_user.username if hasattr(current_user, "username")
        else current_user if current_user else "system"
    )
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE trades SET approval_status = 'approved', updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (updater, entry_id)
    )
    conn.commit()
    conn.close()


def add_ledger_entry(entry_data):
    """
    Legacy single-entry ledger posting.
    Use post_ledger_entries_double_entry for all new entries.
    """
    ok, _reason = compliance_filter_entry(entry_data)
    if not ok:
        return  # Rejected by compliance; do not add

    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    entry_data["broker_code"] = load_broker_code()
    entry_data["account"] = load_account_number()
    if not entry_data.get("group_id"):
        entry_data["group_id"] = entry_data.get("trade_id")
    try:
        qty = float(entry_data.get("quantity") or 0)
        price = float(entry_data.get("price") or 0)
        fee = float(entry_data.get("fee", 0))
        entry_data["total_value"] = round((qty * price) - fee, 2)
    except Exception:
        entry_data["total_value"] = entry_data.get("total_value") or 0
    columns = TRADES_FIELDS
    values = [entry_data.get(col) for col in columns]
    placeholders = ", ".join("?" for _ in columns)
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    conn.close()


# ----------------------------------------------------------------------
# NEW: Reassign a single trade leg's COA account, with audited, non-null event_type
# ----------------------------------------------------------------------
def reassign_leg_account(entry_id: int, new_account_code: str, actor: str, *, reason: str = None, event_type: str = "COA_LEG_REASSIGNED") -> dict:
    """
    Validates the target account, updates trades.account for the given entry_id,
    and appends an immutable audit_trail row with a non-null event_type.

    Returns the updated trade row as a dict.

    Notes:
      - Uses CURRENT_TIMESTAMP (UTC) for updated_at/audit timestamps (SQLite is UTC).
      - Validates new_account_code against COA table if present; requires non-empty code.
      - Does not mutate other fields; double-entry semantics are handled upstream for new postings.
    """
    if not new_account_code or not str(new_account_code).strip():
        raise ValueError("new_account_code is required")

    db_path = _resolve_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # transactional
            # Fetch existing leg
            leg = conn.execute("SELECT * FROM trades WHERE id = ? LIMIT 1", (entry_id,)).fetchone()
            if not leg:
                raise ValueError(f"ledger entry id {entry_id} not found")

            old_account = (leg["account"] if "account" in leg.keys() else None) or ""
            new_code = str(new_account_code).strip()

            # Validate account against COA if available
            if _table_exists(conn, "coa_accounts"):
                exists = conn.execute("SELECT 1 FROM coa_accounts WHERE code = ? LIMIT 1", (new_code,)).fetchone()
                if not exists:
                    raise ValueError(f"invalid account code '{new_code}'")

            # No-op short-circuit (still audit the intent)
            changed = (old_account != new_code)

            # Update trades row (only if changed)
            if changed:
                conn.execute(
                    "UPDATE trades SET account = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_code, actor or "system", entry_id),
                )

            # Prepare dynamic audit insert (only columns that exist)
            if _table_exists(conn, "audit_trail"):
                cols_available = {row[1] for row in conn.execute("PRAGMA table_info(audit_trail)").fetchall()}
                # Always-required set
                cols = ["event_type"]
                vals = [event_type or "COA_LEG_REASSIGNED"]

                # Identity scoping (entity/jurisdiction/broker/bot_id) if present
                entity, juris, broker, bot_id = get_identity_tuple()
                scope_map = {
                    "entity_code": entity,
                    "jurisdiction_code": juris,
                    "broker_code": broker,
                    "bot_id": bot_id,
                }
                for c, v in scope_map.items():
                    if c in cols_available:
                        cols.append(c)
                        vals.append(v)

                # Core audit fields if present
                core_map = {
                    "actor": actor or "system",
                    "reason": reason or "",
                    "entry_id": entry_id,
                    "field": "account",
                    "old_value": old_account,
                    "new_value": new_code,
                }
                for c, v in core_map.items():
                    if c in cols_available:
                        cols.append(c)
                        vals.append(v)

                # Timestamp column variants (prefer created_at, else timestamp_utc)
                if "created_at" in cols_available:
                    cols.append("created_at")
                    vals.append(None)  # use DEFAULT/CURRENT_TIMESTAMP via COALESCE in SQL
                    placeholders = ", ".join(["?"] * (len(cols) - 1) + ["COALESCE(?, CURRENT_TIMESTAMP)"])
                elif "timestamp_utc" in cols_available:
                    cols.append("timestamp_utc")
                    vals.append(None)
                    placeholders = ", ".join(["?"] * (len(cols) - 1) + ["COALESCE(?, CURRENT_TIMESTAMP)"])
                else:
                    placeholders = ", ".join(["?"] * len(cols))

                sql = f"INSERT INTO audit_trail ({', '.join(cols)}) VALUES ({placeholders})"
                conn.execute(sql, vals)

            # Return fresh row
            updated = conn.execute("SELECT * FROM trades WHERE id = ? LIMIT 1", (entry_id,)).fetchone()
            return {k: updated[k] for k in updated.keys()} if updated else {}

    finally:
        conn.close()
