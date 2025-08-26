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

def _pick_representative_leg(trades_group):
    """
    Choose one leg to represent the economic transaction in collapsed view.
    Prefer a 'debit' leg if present (so quantity/price/total_value match the buy/open leg),
    otherwise fall back to the first row.
    """
    if not trades_group:
        return {}
    for t in trades_group:
        try:
            if (t.get("side") or "").lower() == "debit":
                return t
        except Exception:
            pass
    return trades_group[0]

def collapse_group(trades_group):
    """
    Build a collapsed view that shows ONE leg's economics (representative),
    not the sum of both legs. This avoids doubled quantity and total_value=0 issues.
    All original legs are still available in 'sub_entries' (attached later).
    """
    if not trades_group:
        return {}

    rep = _pick_representative_leg(trades_group)
    collapsed = dict(rep)  # start from representative leg

    # Defensive numeric helper
    def _f(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

    # Use representative leg's economics; do NOT sum across legs
    if rep.get("quantity") is None:
        qs = [_f(t.get("quantity")) for t in trades_group if t.get("quantity") is not None]
        collapsed["quantity"] = max(qs) if qs else None
    else:
        collapsed["quantity"] = rep.get("quantity")

    collapsed["price"] = rep.get("price")
    collapsed["total_value"] = rep.get("total_value")
    collapsed["amount"] = rep.get("amount")
    collapsed["fee"] = rep.get("fee")
    collapsed["commission"] = rep.get("commission")

    # Keep metadata for debugging/inspection
    collapsed["sides"] = [t.get("side") for t in trades_group]
    collapsed["ids"] = [t.get("id") for t in trades_group]
    return collapsed

def get_collapsed_groups_by_group_id(limit=100, offset=0):
    groups = get_trades_grouped_by_group_id(None, limit, offset)
    # Always historical order within group
    for g in groups:
        g.sort(key=lambda row: row.get("datetime_utc") or "")
    return [collapse_group(g) for g in groups if g]

def get_collapsed_groups_by_trade_id(limit=100, offset=0):
    groups = get_trades_grouped_by_trade_id(None, limit, offset)
    for g in groups:
        g.sort(key=lambda row: row.get("datetime_utc") or "")
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
        group.sort(key=lambda row: row.get("datetime_utc") or "")  # strict historical order, forensic
        group_id = group[0].get("group_id") if by != "trade_id" else group[0].get("trade_id")
        collapsed_state = collapsed_map.get(group_id, 1)
        force_expand = show_expanded_groups and group_id in show_expanded_groups
        if collapse and collapsed_state and not force_expand:
            collapsed = collapse_group(group)
            collapsed["collapsed"] = True
            collapsed["group_id"] = group_id
            collapsed["sub_entries"] = group
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
    # All returned entries are marked as not collapsed and sorted in historical order
    for entry in group[0] if group else []:
        entry["collapsed"] = False
    if group and group[0]:
        group[0].sort(key=lambda row: row.get("datetime_utc") or "")
        return group[0]
    return []

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
