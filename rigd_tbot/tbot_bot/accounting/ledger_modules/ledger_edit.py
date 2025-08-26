# tbot_bot/accounting/ledger_modules/ledger_edit.py

"""
Ledger edit/update helpers.
Handles updating and deleting ledger entries in the trades table.
All transactional logic (posting, mapping, etc.) is handled elsewhere.
"""

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_web.support.auth_web import get_current_user
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import compliance_filter_ledger_entry

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def edit_ledger_entry(entry_id, updated_data):
    """
    Update a ledger entry in the trades table by ID.
    Accepts a dict of fields to update.
    """
    filtered = compliance_filter_ledger_entry(updated_data)
    if filtered is None:
        return  # Filtered out, do not update
    updated_data = filtered
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
