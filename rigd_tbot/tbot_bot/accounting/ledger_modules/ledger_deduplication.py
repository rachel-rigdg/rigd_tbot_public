# tbot_bot/accounting/ledger_modules/ledger_deduplication.py

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple
from typing import List, Dict, Any

def trade_exists(trade_id, side=None):
    """
    Checks if a trade with the given trade_id and optional side exists in the ledger.
    Returns True if found, else False.
    """
    if not trade_id:
        return False
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        if side:
            result = conn.execute(
                "SELECT 1 FROM trades WHERE trade_id = ? AND side = ? LIMIT 1",
                (trade_id, side)
            ).fetchone()
        else:
            result = conn.execute(
                "SELECT 1 FROM trades WHERE trade_id = ? LIMIT 1",
                (trade_id,)
            ).fetchone()
        return result is not None

def find_duplicate_trades(limit=1000):
    """
    Returns a list of (trade_id, side) pairs that are duplicated in the trades table.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT trade_id, side, COUNT(*) as count
            FROM trades
            WHERE trade_id IS NOT NULL
            GROUP BY trade_id, side
            HAVING count > 1
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [{"trade_id": r[0], "side": r[1], "count": r[2]} for r in rows]

def remove_duplicate_trades():
    """
    Deletes all but one of each duplicate (trade_id, side) pair in the trades table.
    Returns number of deleted rows.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    deleted = 0
    with sqlite3.connect(db_path) as conn:
        duplicates = conn.execute(
            """
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY trade_id, side ORDER BY id) AS rn
                FROM trades
                WHERE trade_id IS NOT NULL
            )
            WHERE rn > 1
            """
        ).fetchall()
        ids_to_delete = [row[0] for row in duplicates]
        if ids_to_delete:
            conn.executemany("DELETE FROM trades WHERE id = ?", [(i,) for i in ids_to_delete])
            deleted = len(ids_to_delete)
            conn.commit()
    return deleted

def check_duplicates(trade_id, side=None):
    """
    Returns count of duplicate (trade_id, side) pairs in the trades table.
    """
    if not trade_id:
        return 0
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        if side:
            row = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE trade_id = ? AND side = ?",
                (trade_id, side)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE trade_id = ?",
                (trade_id,)
            ).fetchone()
        return row[0] if row else 0

# -------- In-memory de-dup for pre-posting (used by tests & sync) --------

def deduplicate_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    In-memory deduplication of normalized broker entries before posting.
    Keeps the first occurrence of each trade_id (pre-double-entry),
    and ensures group_id is populated with trade_id if missing.

    This is intentionally trade_id-only, because post_double_entry()
    will create exactly two legs (debit/credit) per unique trade.
    """
    seen = set()
    result: List[Dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        tid = e.get("trade_id")
        if not tid:
            # If no trade_id, keep it (let compliance/mapping decide later)
            result.append(e)
            continue
        if tid in seen:
            continue
        seen.add(tid)
        if not e.get("group_id"):
            e = dict(e)
            e["group_id"] = tid
        result.append(e)
    return result
