# tbot_bot/accounting/ledger.py


import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def load_internal_ledger():
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT id, date, symbol, type, amount, status FROM ledger_entries")
    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0],
            "date": row[1],
            "symbol": row[2],
            "type": row[3],
            "amount": row[4],
            "status": row[5],
        })
    conn.close()
    return results

def mark_entry_resolved(entry_id):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE ledger_entries SET status = 'ok' WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
