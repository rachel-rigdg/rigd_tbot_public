# tbot_bot/accounting/ledger_modules/ledger_edit.py

"""
Ledger edit/update helpers.

Adds audited COA reassignment for a single leg (entry) while preserving append-only policy
for financial amounts/dates (no mutation to amount/date fields).
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Set, List, Optional

from tbot_bot.support.path_resolver import (
    resolve_ledger_db_path,
    resolve_coa_json_path,
)
from tbot_bot.support.decrypt_secrets import load_bot_identity

# Strict, structured audit (required)
from tbot_bot.accounting.ledger_modules.ledger_audit import append as audit_append  # emits immutable JSONL

# Existing utilities (kept as-is for legacy callers)
from tbot_web.support.auth_web import get_current_user
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import compliance_filter_entry


def get_identity_tuple() -> Tuple[str, str, str, str]:
    identity = load_bot_identity()
    return tuple(identity.split("_"))  # (entity_code, jurisdiction_code, broker_code, bot_id)


# ------------------------
# NEW: audited COA reassignment
# ------------------------
def _active_coa_codes() -> Set[str]:
    """
    Load COA (via path_resolver) and return set of ACTIVE account codes.
    Accepts either:
      - list of account dicts (hierarchical)
      - {"accounts": [...]}
    Accounts are considered active if 'active' missing or truthy.
    """
    import json, os

    p = resolve_coa_json_path()
    if not os.path.exists(p):
        raise FileNotFoundError("COA file not found")

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    def walk(nodes: List[Dict[str, Any]], out: Set[str]):
        for n in nodes or []:
            code = str(n.get("code") or "").strip()
            active = n.get("active", True)
            if code and active:
                out.add(code)
            children = n.get("children") or []
            if isinstance(children, list) and children:
                walk(children, out)

    codes: Set[str] = set()
    if isinstance(data, dict) and isinstance(data.get("accounts"), list):
        walk(data["accounts"], codes)
    elif isinstance(data, list):
        walk(data, codes)
    return codes


def reassign_leg_account(
    entry_id: int,
    new_account_code: str,
    actor: str,
    *,
    reason: Optional[str] = None,
    event_type: str = "COA_LEG_REASSIGNED",
    apply_to_category: bool = False,
    # --- Back-compat: some callers pass `event=` instead of `event_type=` ---
    event: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reassign the COA account for a single ledger leg (row in trades table).

    - Validates new_account_code exists and is active in COA.
    - Updates ONLY 'account' field (no amount/date mutation).
    - Sets WAL + busy_timeout to reduce SQLITE_BUSY on concurrent web/API usage.
    - Emits immutable audit log event with non-empty event label and actor.
    - Returns the UPDATED ROW (dict).
    - If apply_to_category=True, also upserts a programmatic mapping rule derived from this leg.

    Returns: dict row from trades (post-update).
    """
    import time

    def _exec_with_retry(_conn, sql, params=(), attempts=3, sleep_s=0.2):
        last_err = None
        for i in range(attempts):
            try:
                return _conn.execute(sql, params)
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    last_err = e
                    time.sleep(sleep_s)
                    continue
                raise
        # If still failing after retries, raise last error
        raise last_err or sqlite3.OperationalError("database is locked")

    new_account_code = (new_account_code or "").strip()
    if not new_account_code:
        raise ValueError("new_account_code required")

    # Validate COA account active
    active_codes = _active_coa_codes()
    if new_account_code not in active_codes:
        raise ValueError(f"Account code '{new_account_code}' is not active in COA")

    # Choose an audit event label, accepting both `event_type` and legacy `event`
    event_label = (event_type or "").strip() or (event or "").strip()
    if not event_label:
        raise ValueError("event_type (or event) is required for audit")

    # Validate non-empty actor (aligns with stricter audit requirements)
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor is required for audit")

    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)

    ts_utc = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

    # Use WAL + busy timeout for concurrency
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN")

        # Fetch the leg + parent group
        leg = _exec_with_retry(
            conn,
            "SELECT id, group_id, account AS old_account, total_value, datetime_utc, trade_id, symbol, action, strategy "
            "FROM trades WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if not leg:
            raise ValueError(f"Entry id {entry_id} not found")

        old_account = leg["old_account"]

        # Early no-op (but still audit)
        if old_account == new_account_code:
            audit_append(
                event_label,  # positional 'event'
                related_id=entry_id,
                actor=actor,
                group_id=leg["group_id"],
                trade_id=leg["trade_id"],
                before=old_account,
                after=new_account_code,
                reason=reason or "no-op (same account)",
                extra={
                    "old_account_code": old_account,
                    "new_account_code": new_account_code,
                    "symbol": leg["symbol"],
                    "action": leg["action"],
                    "strategy": leg["strategy"],
                    "datetime_utc": leg["datetime_utc"],
                    "amount": leg["total_value"],
                    "source": "web_inline",
                },
            )
            # Return current row (unchanged)
            updated = _exec_with_retry(conn, "SELECT * FROM trades WHERE id = ?", (entry_id,)).fetchone()
            conn.commit()
            return dict(updated)

        # Update ONLY the account field; do not mutate amount/date fields
        _exec_with_retry(
            conn,
            "UPDATE trades SET account = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_account_code, entry_id),
        )

        # Optional: touch group row to invalidate caches if such table exists
        try:
            if leg["group_id"]:
                _exec_with_retry(
                    conn,
                    "UPDATE trade_groups SET updated_at = CURRENT_TIMESTAMP WHERE group_id = ?",
                    (leg["group_id"],),
                )
        except Exception:
            # ignore if trade_groups doesn't exist
            pass

        # Commit DB mutation first
        conn.commit()

        # Structured immutable audit (identity fields injected by audit module)
        audit_append(
            event_label,  # positional 'event'
            related_id=entry_id,
            actor=actor,
            group_id=leg["group_id"],
            trade_id=leg["trade_id"],
            before=old_account,
            after=new_account_code,
            reason=reason,
            extra={
                "old_account_code": old_account,
                "new_account_code": new_account_code,
                "symbol": leg["symbol"],
                "action": leg["action"],
                "strategy": leg["strategy"],
                "datetime_utc": leg["datetime_utc"],
                "amount": leg["total_value"],
                "source": "web_inline",
            },
        )

        # Fetch updated row to return
        updated_row = _exec_with_retry(conn, "SELECT * FROM trades WHERE id = ?", (entry_id,)).fetchone()
        updated_dict = dict(updated_row) if updated_row else {
            "id": entry_id,
            "account": new_account_code,
            "group_id": leg["group_id"],
        }

        # Optionally upsert mapping rule derived from this leg
        if apply_to_category:
            try:
                from tbot_bot.accounting.coa_mapping_table import upsert_rule_from_leg
                upsert_rule_from_leg(dict(updated_row) if updated_row else dict(leg), new_account_code, actor)
            except Exception:
                # Mapping upsert failures must not break the reassignment path
                pass

        return updated_dict

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ------------------------
# Legacy edit/delete (unchanged; retained for backward compatibility)
# ------------------------
def edit_ledger_entry(entry_id, updated_data):
    """
    Update a ledger entry in the trades table by ID.
    Accepts a dict of fields to update.
    """
    ok, _ = compliance_filter_entry(updated_data)
    if not ok:
        return  # Filtered out, do not update

    db_path = resolve_ledger_db_path(*get_identity_tuple())
    current_user = get_current_user()
    updated_data["updated_by"] = (
        current_user.username if hasattr(current_user, "username")
        else current_user if current_user else "system"
    )
    try:
        qty = float(updated_data.get("quantity") or 0)
        price = float(updated_data.get("price") or 0)
        fee = float(updated_data.get("fee") or 0)
        updated_data["total_value"] = round((qty * price) - fee, 2)
    except Exception:
        updated_data["total_value"] = updated_data.get("total_value") or 0
    columns = TRADES_FIELDS
    set_clause = ", ".join([f"{col}=?" for col in columns])
    values = [updated_data.get(col) for col in columns]
    values.append(entry_id)
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"UPDATE trades SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values
    )
    conn.commit()
    conn.close()


def delete_ledger_entry(entry_id):
    """
    Delete a ledger entry from the trades table by ID.
    """
    db_path = resolve_ledger_db_path(*get_identity_tuple())
    conn = sqlite3.connect(db_path)
    conn.execute(
        "DELETE FROM trades WHERE id = ?",
        (entry_id,)
    )
    conn.commit()
    conn.close()
