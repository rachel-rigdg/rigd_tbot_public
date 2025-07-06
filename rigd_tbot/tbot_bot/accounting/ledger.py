# tbot_bot/accounting/ledger.py

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_web.support.auth_web import get_current_user  # to get current user for updated_by etc.

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def load_internal_ledger():
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT id, date, symbol, type, amount, account, trade_id, tags, notes, "
        "CASE WHEN approval_status = 'approved' THEN 'ok' ELSE 'mismatch' END AS status "
        "FROM trades"
    )
    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0],
            "date": row[1],
            "symbol": row[2],
            "type": row[3],
            "amount": row[4],
            "account": row[5],
            "trade_id": row[6],
            "tags": row[7],
            "notes": row[8],
            "status": row[9],
        })
    conn.close()
    return results

def mark_entry_resolved(entry_id):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    current_user = get_current_user()
    updater = current_user.username if current_user else "system"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE trades SET approval_status = 'approved', updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (updater, entry_id)
    )
    conn.commit()
    conn.close()

def add_ledger_entry(entry_data):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    columns = [
        "date", "symbol", "type", "amount", "account", "trade_id", "tags", "notes", "broker",
        "entity_code", "jurisdiction", "created_by", "updated_by", "approved_by", "language",
        "approval_status", "gdpr_compliant", "ccpa_compliant", "pipeda_compliant", "hipaa_sensitive",
        "iso27001_tag", "soc2_type"
    ]
    values = [entry_data.get(col) for col in columns]
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    conn.close()

def edit_ledger_entry(entry_id, updated_data):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    columns = [
        "date", "symbol", "type", "amount", "account", "trade_id", "tags", "notes", "broker",
        "entity_code", "jurisdiction", "updated_by", "language", "approval_status",
        "gdpr_compliant", "ccpa_compliant", "pipeda_compliant", "hipaa_sensitive",
        "iso27001_tag", "soc2_type"
    ]
    set_clause = ", ".join([f"{col}=?" for col in columns])
    values = [updated_data.get(col) for col in columns]
    values.append(entry_id)
    conn.execute(
        f"UPDATE trades SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values
    )
    conn.commit()
    conn.close()

def delete_ledger_entry(entry_id):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "DELETE FROM trades WHERE id = ?",
        (entry_id,)
    )
    conn.commit()
    conn.close()
