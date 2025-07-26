# tbot_bot/accounting/ledger_modules/ledger_query.py

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple

def get_trades_by_group_id(group_id):
    """
    Fetch all trades with the given group_id, ordered by id.
    """
    if not group_id:
        return []
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM trades
            WHERE group_id = ?
            ORDER BY id ASC
            """,
            (group_id,)
        ).fetchall()
        cols = [desc[0] for desc in conn.execute("PRAGMA table_info(trades)")]
        return [dict(zip(cols, row)) for row in rows]

def get_trades_grouped(by="group_id", limit=1000, collapse=False):
    """
    Returns trades grouped by group_id or trade_id.
    If collapse=True, only the first trade of each group is returned.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    if by not in ("group_id", "trade_id"):
        by = "group_id"
    with sqlite3.connect(db_path) as conn:
        if collapse:
            rows = conn.execute(
                f"""
                SELECT * FROM trades t1
                WHERE id = (
                    SELECT MIN(id) FROM trades t2 WHERE t2.{by} = t1.{by}
                )
                AND {by} IS NOT NULL
                ORDER BY t1.id ASC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT * FROM trades
                WHERE {by} IS NOT NULL
                ORDER BY {by}, id
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
        cols = [desc[0] for desc in conn.execute("PRAGMA table_info(trades)")]
        return [dict(zip(cols, row)) for row in rows]

def get_group_ids_for_symbol(symbol, limit=100):
    """
    Returns group_ids for a given symbol, most recent first.
    """
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
    """
    Returns all distinct group_ids, most recent first.
    """
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
