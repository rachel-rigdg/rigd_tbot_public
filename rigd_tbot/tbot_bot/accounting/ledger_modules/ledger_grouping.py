# tbot_bot/accounting/ledger_modules/ledger_grouping.py

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple

def get_trades_grouped_by_group_id(group_id=None, limit=100, offset=0):
    """
    Returns all trades grouped by group_id (or trade_id if group_id is None).
    If group_id is specified, returns only that group.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    results = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if group_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE group_id = ? ORDER BY datetime_utc ASC",
                (group_id,)
            ).fetchall()
            if rows:
                results.append([dict(row) for row in rows])
        else:
            groups = conn.execute(
                "SELECT DISTINCT group_id FROM trades ORDER BY MAX(datetime_utc) DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            for group in groups:
                gid = group["group_id"]
                rows = conn.execute(
                    "SELECT * FROM trades WHERE group_id = ? ORDER BY datetime_utc ASC",
                    (gid,)
                ).fetchall()
                results.append([dict(row) for row in rows])
    return results

def get_trades_grouped_by_trade_id(trade_id=None, limit=100, offset=0):
    """
    Returns all trades grouped by trade_id.
    If trade_id is specified, returns only that group.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    results = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if trade_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE trade_id = ? ORDER BY datetime_utc ASC",
                (trade_id,)
            ).fetchall()
            if rows:
                results.append([dict(row) for row in rows])
        else:
            trades = conn.execute(
                "SELECT DISTINCT trade_id FROM trades ORDER BY MAX(datetime_utc) DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            for t in trades:
                tid = t["trade_id"]
                rows = conn.execute(
                    "SELECT * FROM trades WHERE trade_id = ? ORDER BY datetime_utc ASC",
                    (tid,)
                ).fetchall()
                results.append([dict(row) for row in rows])
    return results

def collapse_group(trades_group):
    """
    For a group (list of dicts), return a single dict with rolled-up sums for
    quantity, total_value, amount, fees, commissions, and a list of sides.
    """
    if not trades_group:
        return {}
    collapsed = dict(trades_group[0])
    collapsed["quantity"] = sum(float(t.get("quantity") or 0) for t in trades_group)
    collapsed["total_value"] = sum(float(t.get("total_value") or 0) for t in trades_group)
    collapsed["amount"] = sum(float(t.get("amount") or 0) for t in trades_group)
    collapsed["fee"] = sum(float(t.get("fee") or 0) for t in trades_group)
    collapsed["commission"] = sum(float(t.get("commission") or 0) for t in trades_group)
    collapsed["sides"] = [t.get("side") for t in trades_group]
    collapsed["ids"] = [t.get("id") for t in trades_group]
    return collapsed

def get_collapsed_groups_by_group_id(limit=100, offset=0):
    """
    Returns collapsed groups by group_id, each as a single dict (for summary UI).
    """
    groups = get_trades_grouped_by_group_id(None, limit, offset)
    return [collapse_group(g) for g in groups if g]

def get_collapsed_groups_by_trade_id(limit=100, offset=0):
    """
    Returns collapsed groups by trade_id, each as a single dict (for summary UI).
    """
    groups = get_trades_grouped_by_trade_id(None, limit, offset)
    return [collapse_group(g) for g in groups if g]
