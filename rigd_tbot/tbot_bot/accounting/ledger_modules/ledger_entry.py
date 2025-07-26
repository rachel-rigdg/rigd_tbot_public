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

def get_identity_tuple():
    identity = load_bot_identity()
    # Defensive: ensure length=4, fill missing with defaults
    parts = identity.split("_") if identity else []
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])

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
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    entry_data["broker_code"] = load_broker_code()
    entry_data["account"] = load_account_number()
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
