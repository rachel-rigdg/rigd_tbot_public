# tbot_bot/accounting/ledger_modules/ledger_grouping.py

from typing import List, Dict, Any, Optional, Tuple
import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple

COLLAPSED_TABLE = "trade_group_collapsed"


def _ensure_collapsed_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {COLLAPSED_TABLE} (
                group_id TEXT PRIMARY KEY,
                collapsed INTEGER NOT NULL
            )
            """
        )
        conn.commit()


def _safe(v: Any) -> Any:
    # Normalize Nones/odd strings so sort comparisons don’t explode
    if v is None:
        return ""
    return v


def _sort_records(rows: List[Dict[str, Any]], sort_by: Optional[str], sort_desc: bool) -> List[Dict[str, Any]]:
    """
    Sort a flat list of rows (collapsed reps or expanded legs).
    Tie-break on datetime_utc to keep chronology stable.
    """
    key = sort_by or "datetime_utc"
    try:
        rows.sort(key=lambda r: (_safe(r.get(key)), _safe(r.get("datetime_utc"))), reverse=bool(sort_desc))
    except Exception:
        # ultra-safe fallback
        rows.sort(key=lambda r: _safe(r.get("datetime_utc")), reverse=bool(sort_desc))
    return rows


def get_trades_grouped_by_group_id(group_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[List[Dict[str, Any]]]:
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    results: List[List[Dict[str, Any]]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if group_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE group_id = ? ORDER BY datetime_utc ASC",
                (group_id,),
            ).fetchall()
            if rows:
                results.append([dict(row) for row in rows])
        else:
            group_rows = conn.execute(
                """
                SELECT group_id, MAX(datetime_utc) AS max_dt
                FROM trades
                WHERE group_id IS NOT NULL AND group_id <> ''
                GROUP BY group_id
                ORDER BY max_dt DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            for group in group_rows:
                gid = group["group_id"]
                rows = conn.execute(
                    "SELECT * FROM trades WHERE group_id = ? ORDER BY datetime_utc ASC",
                    (gid,),
                ).fetchall()
                if rows:
                    results.append([dict(row) for row in rows])
    return results


def get_trades_grouped_by_trade_id(trade_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[List[Dict[str, Any]]]:
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    results: List[List[Dict[str, Any]]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if trade_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE trade_id = ? ORDER BY datetime_utc ASC",
                (trade_id,),
            ).fetchall()
            if rows:
                results.append([dict(row) for row in rows])
        else:
            trade_rows = conn.execute(
                """
                SELECT trade_id, MAX(datetime_utc) AS max_dt
                FROM trades
                WHERE trade_id IS NOT NULL AND trade_id <> ''
                GROUP BY trade_id
                ORDER BY max_dt DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            for t in trade_rows:
                tid = t["trade_id"]
                rows = conn.execute(
                    "SELECT * FROM trades WHERE trade_id = ? ORDER BY datetime_utc ASC",
                    (tid,),
                ).fetchall()
                if rows:
                    results.append([dict(row) for row in rows])
    return results


def _pick_representative_leg(trades_group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Choose one leg to represent the economic transaction in collapsed view.
    Prefer a 'debit' leg (buy/open side). Fallback to the first row.
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


def collapse_group(trades_group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a collapsed view that shows ONE leg's economics (representative),
    not the sum of both legs, to avoid doubling qty and total_value=0 artifacts.
    """
    if not trades_group:
        return {}

    rep = _pick_representative_leg(trades_group)
    collapsed = dict(rep)  # start from representative leg

    # Numeric helper
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

    # Keep metadata for inspection
    collapsed["sides"] = [t.get("side") for t in trades_group]
    collapsed["ids"] = [t.get("id") for t in trades_group]
    return collapsed


def get_collapsed_groups_by_group_id(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    groups = get_trades_grouped_by_group_id(None, limit, offset)
    for g in groups:
        g.sort(key=lambda row: _safe(row.get("datetime_utc")))
    return [collapse_group(g) for g in groups if g]


def get_collapsed_groups_by_trade_id(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    groups = get_trades_grouped_by_trade_id(None, limit, offset)
    for g in groups:
        g.sort(key=lambda row: _safe(row.get("datetime_utc")))
    return [collapse_group(g) for g in groups if g]


def _get_collapsed_map(db_path: str, group_ids: List[str]) -> Dict[str, int]:
    if not group_ids:
        return {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT group_id, collapsed FROM {COLLAPSED_TABLE} WHERE group_id IN ({','.join(['?']*len(group_ids))})",
            tuple(group_ids),
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def fetch_grouped_trades(
    by: str = "group_id",
    collapse: bool = True,
    limit: int = 100,
    offset: int = 0,
    show_expanded_groups: Optional[List[str]] = None,
    *,
    sort_by: Optional[str] = None,
    sort_desc: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fetch grouped trades as either collapsed representatives (with sub_entries) or expanded legs.
    Accepts sort_by/sort_desc to keep the web UI happy. Sorting is applied to the final flat list.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    _ensure_collapsed_table(db_path)

    if by == "trade_id":
        groups = get_trades_grouped_by_trade_id(None, limit, offset)
        group_ids = [g[0].get("trade_id") for g in groups if g]
    else:
        groups = get_trades_grouped_by_group_id(None, limit, offset)
        group_ids = [g[0].get("group_id") for g in groups if g]

    collapsed_map = _get_collapsed_map(db_path, [gid for gid in group_ids if gid])
    result: List[Dict[str, Any]] = []

    for group in groups:
        if not group:
            continue
        # Stable historical order within each group
        group.sort(key=lambda row: _safe(row.get("datetime_utc")))

        group_id = group[0].get("group_id") if by != "trade_id" else group[0].get("trade_id")
        collapsed_state = collapsed_map.get(group_id, 1)
        force_expand = bool(show_expanded_groups) and group_id in show_expanded_groups

        if collapse and collapsed_state and not force_expand:
            collapsed_row = collapse_group(group)
            collapsed_row["collapsed"] = True
            collapsed_row["group_id"] = group_id
            collapsed_row["sub_entries"] = group
            result.append(collapsed_row)
        else:
            # Return each leg, annotated
            for entry in group:
                entry["collapsed"] = False
                entry["group_id"] = group_id
                entry["sub_entries"] = []
            result.extend(group)

    # Apply requested sort to the final flat list
    return _sort_records(result, sort_by, sort_desc)


def fetch_trade_group_by_id(group_id: str, by: str = "group_id") -> List[Dict[str, Any]]:
    if by == "trade_id":
        group = get_trades_grouped_by_trade_id(trade_id=group_id)
    else:
        group = get_trades_grouped_by_group_id(group_id=group_id)
    # Mark as expanded; keep historical order
    rows = group[0] if group else []
    for entry in rows:
        entry["collapsed"] = False
        entry["sub_entries"] = []
    if rows:
        rows.sort(key=lambda row: _safe(row.get("datetime_utc")))
        return rows
    return []


def collapse_expand_group(group_id: str, by: str = "group_id", collapsed_state: Optional[int] = None) -> bool:
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
