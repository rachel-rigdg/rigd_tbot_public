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


def _merge_unique_by_id(base: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge lists of rows, de-duplicating by primary key 'id' if present; otherwise by (trade_id, account, total_value, datetime_utc).
    """
    out: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_fallback = set()

    def _fb_key(r: Dict[str, Any]):
        return (
            r.get("trade_id"),
            r.get("account"),
            str(r.get("total_value")),
            r.get("datetime_utc"),
            r.get("side"),
        )

    for row in (base or []):
        rid = row.get("id")
        if rid is not None:
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
        else:
            key = _fb_key(row)
            if key in seen_fallback:
                continue
            seen_fallback.add(key)
        out.append(row)

    for row in (extra or []):
        rid = row.get("id")
        if rid is not None:
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
        else:
            key = _fb_key(row)
            if key in seen_fallback:
                continue
            seen_fallback.add(key)
        out.append(row)

    return out


def _rows_for_group_id(conn: sqlite3.Connection, group_id: str) -> List[Dict[str, Any]]:
    """
    Primary fetch by group_id, then pull any sibling legs that share the group's trade_id(s)
    but are missing group_id (e.g., P&L third leg or fee splits).
    Any such “extra” legs get group_id patched in-memory for coherent UI grouping.
    """
    if not group_id:
        return []

    conn.row_factory = sqlite3.Row
    primary = conn.execute(
        "SELECT * FROM trades WHERE group_id = ? ORDER BY datetime_utc ASC, id ASC",
        (group_id,),
    ).fetchall()
    primary_rows = [dict(r) for r in primary]

    if not primary_rows:
        return []

    trade_ids = sorted({r.get("trade_id") for r in primary_rows if r.get("trade_id")})
    extra_rows: List[Dict[str, Any]] = []
    if trade_ids:
        # Legs that share trade_ids but have missing/blank group_id (commonly P&L or fee lines)
        placeholders = ",".join(["?"] * len(trade_ids))
        extras = conn.execute(
            f"""
            SELECT * FROM trades
            WHERE trade_id IN ({placeholders})
              AND (group_id IS NULL OR group_id = '')
            ORDER BY datetime_utc ASC, id ASC
            """,
            tuple(trade_ids),
        ).fetchall()
        for r in extras or []:
            rowd = dict(r)
            # Patch for UI coherence; DO NOT persist to DB here
            rowd["group_id"] = group_id
            extra_rows.append(rowd)

    return _merge_unique_by_id(primary_rows, extra_rows)


def _rows_for_trade_id(conn: sqlite3.Connection, trade_id: str) -> List[Dict[str, Any]]:
    """
    Primary fetch by trade_id, then (if a group_id exists on any leg) pull all legs in that group_id.
    This makes a trade-centric view also show the associated P&L/fee legs.
    """
    if not trade_id:
        return []

    conn.row_factory = sqlite3.Row
    primary = conn.execute(
        "SELECT * FROM trades WHERE trade_id = ? ORDER BY datetime_utc ASC, id ASC",
        (trade_id,),
    ).fetchall()
    primary_rows = [dict(r) for r in primary]

    if not primary_rows:
        return []

    # If any primary leg has a group_id, also include the whole group
    group_ids = sorted({r.get("group_id") for r in primary_rows if r.get("group_id")})
    group_rows: List[Dict[str, Any]] = []
    for gid in group_ids:
        if not gid:
            continue
        group_rows.extend(_rows_for_group_id(conn, gid))

    merged = _merge_unique_by_id(primary_rows, group_rows)
    # Ensure all merged rows have group_id (patch with first non-empty if missing)
    canonical_gid = next((r.get("group_id") for r in merged if r.get("group_id")), None)
    if canonical_gid:
        for r in merged:
            if not r.get("group_id"):
                r["group_id"] = canonical_gid
    return merged


def get_trades_grouped_by_group_id(group_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[List[Dict[str, Any]]]:
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    results: List[List[Dict[str, Any]]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if group_id:
            rows = _rows_for_group_id(conn, group_id)
            if rows:
                results.append(rows)
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
                rows = _rows_for_group_id(conn, gid)
                if rows:
                    results.append(rows)
    return results


def get_trades_grouped_by_trade_id(trade_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[List[Dict[str, Any]]]:
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    results: List[List[Dict[str, Any]]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if trade_id:
            rows = _rows_for_trade_id(conn, trade_id)
            if rows:
                results.append(rows)
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
                rows = _rows_for_trade_id(conn, tid)
                if rows:
                    results.append(rows)
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
    not the sum of both/all legs, to avoid doubling qty and total_value=0 artifacts.
    Sub-entries remain intact and include cash/basis/P&L (and fee line if separate).
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
    Ensures that “third” legs (e.g., realized P&L) that share trade_id with the group
    are included and carry group_id in-memory so the UI shows: cash, basis, P&L (and fee line if separate).
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    _ensure_collapsed_table(db_path)

    results: List[Dict[str, Any]] = []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if by == "trade_id":
            groups = get_trades_grouped_by_trade_id(None, limit, offset)
            group_ids = [g[0].get("trade_id") for g in groups if g]
        else:
            groups = get_trades_grouped_by_group_id(None, limit, offset)
            group_ids = [g[0].get("group_id") for g in groups if g]

    collapsed_map = _get_collapsed_map(db_path, [gid for gid in group_ids if gid])

    # We must re-fetch full groups with augmentation, so bring a connection back
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if by == "trade_id":
            # Build from trade-centric batches with augmented siblings
            seed_rows = conn.execute(
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
            for t in seed_rows:
                tid = t["trade_id"]
                group = _rows_for_trade_id(conn, tid)
                if not group:
                    continue
                group_id = group[0].get("group_id") or tid
                collapsed_state = collapsed_map.get(group_id, 1)
                force_expand = bool(show_expanded_groups) and group_id in (show_expanded_groups or [])
                group.sort(key=lambda row: _safe(row.get("datetime_utc")))
                if collapse and collapsed_state and not force_expand:
                    collapsed_row = collapse_group(group)
                    collapsed_row["collapsed"] = True
                    collapsed_row["group_id"] = group_id
                    collapsed_row["sub_entries"] = group
                    results.append(collapsed_row)
                else:
                    for entry in group:
                        entry["collapsed"] = False
                        entry["group_id"] = group_id
                        entry["sub_entries"] = []
                    results.extend(group)
        else:
            # Build from group-centric batches with augmentation
            seed_rows = conn.execute(
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
            for g in seed_rows:
                gid = g["group_id"]
                group = _rows_for_group_id(conn, gid)
                if not group:
                    continue
                collapsed_state = collapsed_map.get(gid, 1)
                force_expand = bool(show_expanded_groups) and gid in (show_expanded_groups or [])
                group.sort(key=lambda row: _safe(row.get("datetime_utc")))
                if collapse and collapsed_state and not force_expand:
                    collapsed_row = collapse_group(group)
                    collapsed_row["collapsed"] = True
                    collapsed_row["group_id"] = gid
                    collapsed_row["sub_entries"] = group
                    results.append(collapsed_row)
                else:
                    for entry in group:
                        entry["collapsed"] = False
                        entry["group_id"] = gid
                        entry["sub_entries"] = []
                    results.extend(group)

    # Apply requested sort to the final flat list
    return _sort_records(results, sort_by, sort_desc)


def fetch_trade_group_by_id(group_id: str, by: str = "group_id") -> List[Dict[str, Any]]:
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        if by == "trade_id":
            rows = _rows_for_trade_id(conn, group_id)
        else:
            rows = _rows_for_group_id(conn, group_id)
    # Mark as expanded; keep historical order
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
