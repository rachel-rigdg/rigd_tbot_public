# tbot_bot/accounting/ledger_modules/ledger_grouping.py

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple

COLLAPSED_TABLE = "trade_group_collapsed"

def _ensure_collapsed_table(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {COLLAPSED_TABLE} (
                group_id TEXT PRIMARY KEY,
                collapsed INTEGER NOT NULL
            )
            """
        )

def get_trades_grouped_by_group_id(group_id=None, limit=100, offset=0):
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
            group_rows = conn.execute(
                "SELECT group_id, MAX(datetime_utc) as max_dt FROM trades WHERE group_id IS NOT NULL GROUP BY group_id ORDER BY max_dt DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            for group in group_rows:
                gid = group["group_id"]
                rows = conn.execute(
                    "SELECT * FROM trades WHERE group_id = ? ORDER BY datetime_utc ASC",
                    (gid,)
                ).fetchall()
                results.append([dict(row) for row in rows])
    return results

def get_trades_grouped_by_trade_id(trade_id=None, limit=100, offset=0):
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
            trade_rows = conn.execute(
                "SELECT trade_id, MAX(datetime_utc) as max_dt FROM trades WHERE trade_id IS NOT NULL GROUP BY trade_id ORDER BY max_dt DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            for t in trade_rows:
                tid = t["trade_id"]
                rows = conn.execute(
                    "SELECT * FROM trades WHERE trade_id = ? ORDER BY datetime_utc ASC",
                    (tid,)
                ).fetchall()
                results.append([dict(row) for row in rows])
    return results

def collapse_group(trades_group):
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
    groups = get_trades_grouped_by_group_id(None, limit, offset)
    return [collapse_group(g) for g in groups if g]

def get_collapsed_groups_by_trade_id(limit=100, offset=0):
    groups = get_trades_grouped_by_trade_id(None, limit, offset)
    return [collapse_group(g) for g in groups if g]

def _get_collapsed_map(db_path, group_ids):
    if not group_ids:
        return {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT group_id, collapsed FROM {COLLAPSED_TABLE} WHERE group_id IN ({','.join(['?']*len(group_ids))})",
            tuple(group_ids)
        ).fetchall()
    return {row[0]: row[1] for row in rows}

def fetch_grouped_trades(by="group_id", collapse=True, limit=100, offset=0, show_expanded_groups=None):
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    _ensure_collapsed_table(db_path)

    if by == "trade_id":
        groups = get_trades_grouped_by_trade_id(None, limit, offset)
        group_ids = [g[0].get("trade_id") for g in groups if g]
    else:
        groups = get_trades_grouped_by_group_id(None, limit, offset)
        group_ids = [g[0].get("group_id") for g in groups if g]

    collapsed_map = _get_collapsed_map(db_path, group_ids)
    result = []

    for group in groups:
        if not group:
            continue
        group_id = group[0].get("group_id") if by != "trade_id" else group[0].get("trade_id")
        collapsed_state = collapsed_map.get(group_id, 1)
        force_expand = show_expanded_groups and group_id in show_expanded_groups
        if collapse and collapsed_state and not force_expand:
            collapsed = collapse_group(group)
            collapsed["collapsed"] = True
            collapsed["group_id"] = group_id
            collapsed["sub_entries"] = group  # include for audit, UI can ignore if not needed
            result.append(collapsed)
        else:
            for entry in group:
                entry["collapsed"] = False
                entry["group_id"] = group_id
                entry["sub_entries"] = []
            result.extend(group)
    return result

def fetch_trade_group_by_id(group_id, by="group_id"):
    if by == "trade_id":
        group = get_trades_grouped_by_trade_id(trade_id=group_id)
    else:
        group = get_trades_grouped_by_group_id(group_id=group_id)
    # All returned entries are marked as not collapsed
    for entry in group[0] if group else []:
        entry["collapsed"] = False
    return group[0] if group else []

def collapse_expand_group(group_id, by="group_id", collapsed_state=None):
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    _ensure_collapsed_table(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT collapsed FROM {COLLAPSED_TABLE} WHERE group_id = ?", (group_id,))
        row = cur.fetchone()
        if row:
            prev_state = bool(row[0])
            new_state = int(not prev_state) if collapsed_state is None else int(bool(collapsed_state))
            cur.execute(f"UPDATE {COLLAPSED_TABLE} SET collapsed = ? WHERE group_id = ?", (new_state, group_id))
        else:
            new_state = 0 if collapsed_state is None else int(bool(collapsed_state))
            cur.execute(f"INSERT INTO {COLLAPSED_TABLE} (group_id, collapsed) VALUES (?, ?)", (group_id, new_state))
        conn.commit()
    return True
