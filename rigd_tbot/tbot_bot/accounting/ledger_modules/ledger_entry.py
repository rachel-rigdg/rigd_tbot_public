# tbot_bot/accounting/ledger_modules/ledger_entry.py

"""
Legacy single-entry ledger helpers.
All new posting/editing/deleting must use double-entry and helpers in ledger_double_entry.py / ledger_edit.py.
"""

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_web.support.auth_web import get_current_user
from tbot_bot.accounting.ledger_modules.ledger_account_map import load_broker_code, load_account_number
from tbot_bot.accounting.ledger_modules.ledger_edit import edit_ledger_entry, delete_ledger_entry  # Use shared helpers

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def load_internal_ledger():
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT id, ledger_entry_id, datetime_utc, symbol, action, quantity, price, total_value, "
        "fee, "
        "broker_code, strategy, account, trade_id, tags, notes, jurisdiction_code, entity_code, language, "
        "created_by, updated_by, approved_by, approval_status, gdpr_compliant, ccpa_compliant, "
        "pipeda_compliant, hipaa_sensitive, iso27001_tag, soc2_type, created_at, updated_at, "
        "'ok' AS status, json_metadata "
        "FROM trades"
    )
    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0],
            "ledger_entry_id": row[1],
            "datetime_utc": row[2],
            "symbol": row[3],
            "action": row[4],
            "quantity": row[5],
            "price": row[6],
            "total_value": row[7],
            "fee": row[8],
            "broker": row[9],
            "strategy": row[10],
            "account": row[11],
            "trade_id": row[12],
            "tags": row[13],
            "notes": row[14],
            "jurisdiction_code": row[15],
            "entity_code": row[16],
            "language": row[17],
            "created_by": row[18],
            "updated_by": row[19],
            "approved_by": row[20],
            "approval_status": row[21],
            "gdpr_compliant": row[22],
            "ccpa_compliant": row[23],
            "pipeda_compliant": row[24],
            "hipaa_sensitive": row[25],
            "iso27001_tag": row[26],
            "soc2_type": row[27],
            "created_at": row[28],
            "updated_at": row[29],
            "status": row[30],
            "json_metadata": row[31],
        })
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
        fee = float(entry_data.get("fee") or 0)
        entry_data["total_value"] = round((qty * price) - fee, 2)
    except Exception:
        entry_data["total_value"] = entry_data.get("total_value") or 0
    columns = [
        "ledger_entry_id", "datetime_utc", "symbol", "action", "quantity", "price", "total_value", "fee", "broker_code",
        "strategy", "account", "trade_id", "tags", "notes", "jurisdiction_code", "entity_code", "language",
        "created_by", "updated_by", "approved_by", "approval_status", "gdpr_compliant", "ccpa_compliant",
        "pipeda_compliant", "hipaa_sensitive", "iso27001_tag", "soc2_type", "json_metadata"
    ]
    values = [entry_data.get(col) for col in columns]
    placeholders = ", ".join("?" for _ in columns)
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    conn.close()
