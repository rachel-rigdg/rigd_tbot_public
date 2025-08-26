# tbot_bot/accounting/ledger_modules/ledger_query.py

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple
from tbot_bot.accounting.ledger_modules.ledger_grouping import fetch_grouped_trades as grouping_fetch_grouped_trades, fetch_trade_group_by_id as grouping_fetch_trade_group_by_id

PRIMARY_FIELDS = ("symbol", "datetime_utc", "action", "price", "quantity", "total_value")

def _is_blank_entry(entry):
    return all(
        entry.get(f) is None or str(entry.get(f)).strip() == "" for f in PRIMARY_FIELDS
    )

def fetch_grouped_trades(*args, **kwargs):
    return grouping_fetch_grouped_trades(*args, **kwargs)

def fetch_trade_group_by_id(group_id):
    return grouping_fetch_trade_group_by_id(group_id)

def search_trades(search_term=None, sort_by="datetime_utc", sort_desc=True, limit=1000):
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    order_dir = "DESC" if sort_desc else "ASC"
    query = f"SELECT * FROM trades"
    params = []
    if search_term:
        query += " WHERE symbol LIKE ? OR trade_id LIKE ? OR notes LIKE ?"
        params += [f"%{search_term}%"] * 3
    query += f" ORDER BY {sort_by} {order_dir} LIMIT ?"
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
        cols = [desc[1] for desc in conn.execute("PRAGMA table_info(trades)")]
        trades = [dict(zip(cols, row)) for row in rows]
        trades = [t for t in trades if not _is_blank_entry(t)]
        return trades

def get_group_ids_for_symbol(symbol, limit=100):
    if not symbol:
        return []
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT group_id
            FROM trades
            WHERE symbol = ?
            AND group_id IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (symbol, limit)
        ).fetchall()
        return [row[0] for row in rows if row[0] is not None]

def get_all_group_ids(limit=1000):
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT group_id
            FROM trades
            WHERE group_id IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [row[0] for row in rows if row[0] is not None]
