# tbot_bot/accounting/ledger/ledger_edit.py

"""
Ledger edit/update helpers.
Handles updating and deleting ledger entries in the trades table.
All transactional logic (posting, mapping, etc.) is handled elsewhere.
"""

import sqlite3
from tbot_bot.accounting.ledger.ledger_core import get_ledger_db_path
from tbot_web.support.auth_web import get_current_user

def edit_ledger_entry(entry_id, updated_data):
    """
    Update a ledger entry in the trades table by ID.
    Accepts a dict of fields to update.
    """
    db_path = get_ledger_db_path()
    try:
        qty = float(updated_data.get("quantity") or 0)
        price = float(updated_data.get("price") or 0)
        fee = float(updated_data.get("fee") or 0)
        updated_data["total_value"] = round((qty * price) - fee, 2)
    except Exception:
        updated_data["total_value"] = updated_data.get("total_value") or 0
    columns = [
        "ledger_entry_id", "datetime_utc", "symbol", "action", "quantity", "price", "total_value", "fee", "broker_code",
        "strategy", "account", "trade_id", "tags", "notes", "jurisdiction", "entity_code", "language",
        "updated_by", "approval_status", "gdpr_compliant", "ccpa_compliant", "pipeda_compliant",
        "hipaa_sensitive", "iso27001_tag", "soc2_type", "json_metadata"
    ]
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
    db_path = get_ledger_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "DELETE FROM trades WHERE id = ?",
        (entry_id,)
    )
    conn.commit()
    conn.close()
