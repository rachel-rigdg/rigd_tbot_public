# tbot_bot/accounting/ledger_modules/ledger_grouping.py
"""
Grouping helpers (v048, patched)
- Generate/propagate group_id (UUIDv4 or deterministic from FITID set).
- Helpers to group related splits and link reconciliation_log metadata.
- Dynamic timestamp detection so queries work even if some *_utc columns are absent.
"""

from __future__ import annotations

import uuid
import sqlite3
from typing import Dict, Iterable, List, Optional, Tuple

from tbot_bot.accounting.ledger_modules.ledger_core import get_conn, get_identity_tuple

COLLAPSED_TABLE = "trade_group_collapsed"  # keep existing name for compatibility


# -----------------
# timestamp helpers
# -----------------

def _present_ts_cols_for_table(conn: sqlite3.Connection, table: str) -> List[str]:
    """Return timestamp-like columns that actually exist on the given table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = {r[1] for r in rows}  # r[1] is 'name'
    ordered = ["timestamp_utc", "datetime_utc", "created_at_utc"]
    return [c for c in ordered if c in cols]


def _ts_expr_for_table(conn: sqlite3.Connection, table: str) -> str:
    """
    Build a safe SQL expression for ordering/filtering by time without referencing
    columns that do not exist (SQLite errors at parse time if they don't).
    """
    cols = _present_ts_cols_for_table(conn, table)
    if not cols:
        return "id"  # absolute fallback to stable order
    if len(cols) == 1:
        return cols[0]
    return "COALESCE(" + ", ".join(cols) + ")"


# -----------------
# group_id helpers
# -----------------

def generate_group_id(entries: Iterable[Dict]) -> str:
    """
    If all entries have a FITID, generate deterministic UUIDv5 from sorted FITIDs.
    Otherwise return a random UUIDv4.
    """
    items = list(entries)
    fitids = sorted([str(e.get("fitid")).strip() for e in items if e and e.get("fitid")])
    if items and len(fitids) == len(items):
        seed = "|".join(fitids)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rigd-tbot-group:{seed}"))
    return str(uuid.uuid4())


def propagate_group_id(entries: List[Dict], group_id: Optional[str] = None) -> Tuple[str, List[Dict]]:
    """
    Ensure each entry has a group_id. Returns (group_id, updated_entries).
    """
    if not group_id:
        group_id = generate_group_id(entries)
    updated: List[Dict] = []
    for e in entries:
        ee = dict(e)
        ee.setdefault("group_id", group_id)
        updated.append(ee)
    return group_id, updated


# -----------------
# storage helpers
# -----------------

def _ensure_collapsed_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {COLLAPSED_TABLE} (
            group_id TEXT PRIMARY KEY,
            collapsed INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def _rows_to_dicts(rows) -> List[Dict]:
    return [{k: row[k] for k in row.keys()} for row in rows]


# -----------------
# reconciliation links
# -----------------

def _fetch_reconciliation_map(conn: sqlite3.Connection, group_ids: List[str]) -> Dict[str, Dict]:
    """
    Return latest reconciliation info per group_id if table exists.
    Keys: group_id → {status, sync_run_id, mapping_version, last_ts}
    """
    if not group_ids:
        return {}
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reconciliation_log'"
        ).fetchone()
        if not exists:
            return {}
    except Exception:
        return {}

    ts_expr = _ts_expr_for_table(conn, "reconciliation_log")
    q = f"""
        SELECT group_id,
               MAX({ts_expr}) AS last_ts,
               COALESCE(status,'') AS status,
               COALESCE(sync_run_id,'') AS sync_run_id,
               COALESCE(mapping_version,'') AS mapping_version
          FROM reconciliation_log
         WHERE group_id IN ({",".join(["?"]*len(group_ids))})
         GROUP BY group_id
    """
    rows = conn.execute(q, tuple(group_ids)).fetchall()
    out: Dict[str, Dict] = {}
    for r in rows:
        out[r["group_id"]] = {
            "status": r["status"],
            "sync_run_id": r["sync_run_id"],
            "mapping_version": r["mapping_version"],
            "last_ts": r["last_ts"],
        }
    return out


def attach_reconciliation_to_groups(groups: List[List[Dict]]) -> List[List[Dict]]:
    """
    For each group (list of splits), attach 'reconciliation' dict to the first element.
    """
    if not groups:
        return groups
    group_ids: List[str] = []
    for g in groups:
        if g:
            gid = g[0].get("group_id") or g[0].get("trade_id")
            if gid:
                group_ids.append(gid)

    with get_conn() as conn:
        conn.row_factory = __import__("sqlite3").Row
        recon_map = _fetch_reconciliation_map(conn, group_ids)

    for g in groups:
        if not g:
            continue
        gid = g[0].get("group_id") or g[0].get("trade_id")
        if gid and gid in recon_map:
            g[0]["reconciliation"] = recon_map[gid]
    return groups


# -----------------
# grouping queries (identity-scoped + dynamic timestamps)
# -----------------

def _identity_where() -> Tuple[str, Tuple[str, str, str]]:
    ec, jc, bc, _ = get_identity_tuple()
    return "entity_code = ? AND jurisdiction_code = ? AND broker_code = ?", (ec, jc, bc)


def get_trades_grouped_by_group_id(
    group_id: Optional[str] = None, limit: int = 100, offset: int = 0
) -> List[List[Dict]]:
    """
    Return trades grouped by group_id, ordered within each group by time ascending.
    """
    results: List[List[Dict]] = []
    with get_conn() as conn:
        conn.row_factory = __import__("sqlite3").Row
        ts_expr = _ts_expr_for_table(conn, "trades")
        where_ident, ident_params = _identity_where()

        if group_id:
            rows = conn.execute(
                f"""
                SELECT * FROM trades
                 WHERE {where_ident} AND group_id = ?
                 ORDER BY {ts_expr} ASC, id ASC
                """,
                ident_params + (group_id,),
            ).fetchall()
            if rows:
                results.append(_rows_to_dicts(rows))
        else:
            groups = conn.execute(
                f"""
                SELECT group_id, MAX({ts_expr}) AS max_dt
                  FROM trades
                 WHERE {where_ident} AND group_id IS NOT NULL
                 GROUP BY group_id
                 ORDER BY max_dt DESC, group_id DESC
                 LIMIT ? OFFSET ?
                """,
                ident_params + (int(limit), int(offset)),
            ).fetchall()
            for g in groups:
                gid = g["group_id"]
                rows = conn.execute(
                    f"""
                    SELECT * FROM trades
                     WHERE {where_ident} AND group_id = ?
                     ORDER BY {ts_expr} ASC, id ASC
                    """,
                    ident_params + (gid,),
                ).fetchall()
                if rows:
                    results.append(_rows_to_dicts(rows))
    return results


def get_trades_grouped_by_trade_id(
    trade_id: Optional[str] = None, limit: int = 100, offset: int = 0
) -> List[List[Dict]]:
    """
    Return trades grouped by trade_id, ordered within each group by time ascending.
    """
    results: List[List[Dict]] = []
    with get_conn() as conn:
        conn.row_factory = __import__("sqlite3").Row
        ts_expr = _ts_expr_for_table(conn, "trades")
        where_ident, ident_params = _identity_where()

        if trade_id:
            rows = conn.execute(
                f"""
                SELECT * FROM trades
                 WHERE {where_ident} AND trade_id = ?
                 ORDER BY {ts_expr} ASC, id ASC
                """,
                ident_params + (trade_id,),
            ).fetchall()
            if rows:
                results.append(_rows_to_dicts(rows))
        else:
            groups = conn.execute(
                f"""
                SELECT trade_id, MAX({ts_expr}) AS max_dt
                  FROM trades
                 WHERE {where_ident} AND trade_id IS NOT NULL
                 GROUP BY trade_id
                 ORDER BY max_dt DESC, trade_id DESC
                 LIMIT ? OFFSET ?
                """,
                ident_params + (int(limit), int(offset)),
            ).fetchall()
            for g in groups:
                tid = g["trade_id"]
                rows = conn.execute(
                    f"""
                    SELECT * FROM trades
                     WHERE {where_ident} AND trade_id = ?
                     ORDER BY {ts_expr} ASC, id ASC
                    """,
                    ident_params + (tid,),
                ).fetchall()
                if rows:
                    results.append(_rows_to_dicts(rows))
    return results


# -----------------
# collapse helpers
# -----------------

def _pick_representative_leg(trades_group: List[Dict]) -> Dict:
    if not trades_group:
        return {}
    for t in trades_group:
        try:
            if (t.get("side") or "").lower() == "debit":
                return t
        except Exception:
            pass
    return trades_group[0]


def collapse_group(trades_group: List[Dict]) -> Dict:
    """
    Build a collapsed view that shows ONE leg's economics (representative).
    """
    if not trades_group:
        return {}
    rep = _pick_representative_leg(trades_group)
    collapsed = dict(rep)

    def _f(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

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

    collapsed["sides"] = [t.get("side") for t in trades_group]
    collapsed["ids"] = [t.get("id") for t in trades_group]
    return collapsed


def get_collapsed_groups_by_group_id(limit: int = 100, offset: int = 0) -> List[Dict]:
    groups = get_trades_grouped_by_group_id(None, limit, offset)
    for g in groups:
        g.sort(key=lambda row: ((row.get("timestamp_utc") or row.get("datetime_utc") or row.get("created_at_utc") or ""), row.get("id") or 0))
    return [collapse_group(g) for g in groups if g]


def get_collapsed_groups_by_trade_id(limit: int = 100, offset: int = 0) -> List[Dict]:
    groups = get_trades_grouped_by_trade_id(None, limit, offset)
    for g in groups:
        g.sort(key=lambda row: ((row.get("timestamp_utc") or row.get("datetime_utc") or row.get("created_at_utc") or ""), row.get("id") or 0))
    return [collapse_group(g) for g in groups if g]


# -----------------
# UI helpers with collapse state + reconciliation
# -----------------

def _get_collapsed_map(conn: sqlite3.Connection, group_ids: List[str]) -> Dict[str, int]:
    if not group_ids:
        return {}
    rows = conn.execute(
        f"SELECT group_id, collapsed FROM {COLLAPSED_TABLE} WHERE group_id IN ({','.join(['?']*len(group_ids))})",
        tuple(group_ids),
    ).fetchall()
    return {row[0]: int(row[1]) for row in rows}


def fetch_grouped_trades(
    by: str = "group_id",
    collapse: bool = True,
    limit: int = 100,
    offset: int = 0,
    show_expanded_groups: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Fetch grouped trades, optionally collapsed, with reconciliation metadata attached.
    """
    with get_conn() as conn:
        _ensure_collapsed_table(conn)

        if by == "trade_id":
            groups = get_trades_grouped_by_trade_id(None, limit, offset)
            group_ids = [g[0].get("trade_id") for g in groups if g]
        else:
            groups = get_trades_grouped_by_group_id(None, limit, offset)
            group_ids = [g[0].get("group_id") for g in groups if g]

        collapsed_map = _get_collapsed_map(conn, group_ids)
        groups = attach_reconciliation_to_groups(groups)

        result: List[Dict] = []
        for group in groups:
            if not group:
                continue
            group.sort(key=lambda row: ((row.get("timestamp_utc") or row.get("datetime_utc") or row.get("created_at_utc") or ""), row.get("id") or 0))
            group_id = group[0].get("group_id") if by != "trade_id" else group[0].get("trade_id")
            collapsed_state = collapsed_map.get(group_id, 1)
            force_expand = show_expanded_groups and group_id in show_expanded_groups
            if collapse and collapsed_state and not force_expand:
                collapsed_row = collapse_group(group)
                collapsed_row["collapsed"] = True
                collapsed_row["group_id"] = group_id
                collapsed_row["sub_entries"] = group
                if "reconciliation" in group[0]:
                    collapsed_row["reconciliation"] = group[0]["reconciliation"]
                result.append(collapsed_row)
            else:
                for entry in group:
                    entry["collapsed"] = False
                    entry["group_id"] = group_id
                    entry.setdefault("sub_entries", [])
                result.extend(group)
        return result


def fetch_trade_group_by_id(group_id: str, by: str = "group_id") -> List[Dict]:
    """
    Fetch a single group by group_id or trade_id, sorted ascending.
    """
    if by == "trade_id":
        group = get_trades_grouped_by_trade_id(trade_id=group_id)
    else:
        group = get_trades_grouped_by_group_id(group_id=group_id)
    for entry in group[0] if group else []:
        entry["collapsed"] = False
    if group and group[0]:
        group[0].sort(key=lambda row: ((row.get("timestamp_utc") or row.get("datetime_utc") or row.get("created_at_utc") or ""), row.get("id") or 0))
        return group[0]
    return []


def collapse_expand_group(group_id: str, by: str = "group_id", collapsed_state: Optional[bool] = None) -> bool:
    """
    Toggle or set the collapsed state for a group in the UI helper table.
    """
    with get_conn() as conn:
        _ensure_collapsed_table(conn)
        cur = conn.execute(f"SELECT collapsed FROM {COLLAPSED_TABLE} WHERE group_id = ?", (group_id,))
        row = cur.fetchone()
        if row:
            prev_state = bool(int(row[0]))
            new_state = int(not prev_state) if collapsed_state is None else int(bool(collapsed_state))
            conn.execute(f"UPDATE {COLLAPSED_TABLE} SET collapsed = ? WHERE group_id = ?", (new_state, group_id))
        else:
            new_state = 0 if collapsed_state is None else int(bool(collapsed_state))
            conn.execute(f"INSERT INTO {COLLAPSED_TABLE} (group_id, collapsed) VALUES (?, ?)", (group_id, new_state))
        conn.commit()
    return True
