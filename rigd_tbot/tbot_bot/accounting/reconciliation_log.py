# tbot_bot/accounting/reconciliation_log.py
# Reconciliation log (v048): append-only audit of broker↔ledger reconciliation.
# - Statuses: matched, missing_broker, missing_ledger, corrected, rejected
# - Stores sync_run_id, api_hash, mapping_version, group_id, UTC stamps, diff JSON
# - Export diffs by time window
# - Index on (sync_run_id, group_id)

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

ALLOWED_STATUSES = {"matched", "missing_broker", "missing_ledger", "corrected", "rejected"}

RECON_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT,
    group_id TEXT,
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL,
    broker_code TEXT NOT NULL,
    broker TEXT,
    error_code TEXT,
    account_id TEXT,
    statement_date TEXT,
    ledger_balance REAL,
    ledger_entry_id TEXT,
    broker_balance REAL,
    delta REAL,
    status TEXT NOT NULL CHECK(status IN ('matched','missing_broker','missing_ledger','corrected','rejected')),
    resolution TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    raw_record TEXT,
    notes TEXT,
    recon_type TEXT,
    raw_record_json TEXT DEFAULT '{}',
    compare_fields TEXT DEFAULT '{}',
    diff_json TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}',
    timestamp_utc TEXT NOT NULL,
    sync_run_id TEXT,
    api_hash TEXT,
    imported_at TEXT,
    updated_at TEXT,
    user_action TEXT,
    mapping_version TEXT
);
"""

RECON_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_recon_sync_group ON reconciliation_log(sync_run_id, group_id);",
    "CREATE INDEX IF NOT EXISTS idx_recon_ts ON reconciliation_log(timestamp_utc);",
    "CREATE INDEX IF NOT EXISTS idx_recon_trade ON reconciliation_log(trade_id);",
]

def _get_db_path() -> str:
    entity_code, jurisdiction_code, broker_code, bot_id = str(get_bot_identity()).split("_")
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _json_dump(obj: Any) -> str:
    try:
        return json.dumps(obj if obj is not None else {}, ensure_ascii=False, default=str)
    except Exception:
        return "{}"

def init_reconciliation_log_table() -> None:
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(RECON_TABLE_SCHEMA)
        for ddl in RECON_INDEXES:
            conn.execute(ddl)
        conn.commit()

def ensure_reconciliation_log_initialized() -> None:
    init_reconciliation_log_table()

def log_reconciliation_entry(
    *,
    trade_id: Optional[str],
    status: str,
    compare_fields: Optional[Dict[str, Any]] = None,
    diff: Optional[Dict[str, Any]] = None,
    sync_run_id: Optional[str] = None,
    api_hash: Optional[str] = None,
    broker: Optional[str] = None,
    raw_record: Optional[Dict[str, Any]] = None,
    mapping_version: Optional[str] = None,
    notes: Optional[str] = None,
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    group_id: Optional[str] = None,
    error_code: Optional[str] = None,
    account_id: Optional[str] = None,
    statement_date: Optional[str] = None,
    ledger_balance: Optional[float] = None,
    ledger_entry_id: Optional[str] = None,
    broker_balance: Optional[float] = None,
    delta: Optional[float] = None,
    resolution: Optional[str] = None,
    resolved_by: Optional[str] = None,
    resolved_at: Optional[str] = None,
    raw_record_text: Optional[str] = None,
    recon_type: Optional[str] = None,
    json_metadata: Optional[Dict[str, Any]] = None,
    imported_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    user_action: Optional[str] = None,
) -> None:
    """
    Append a reconciliation entry (append-only).
    - Validates status against ALLOWED_STATUSES.
    - Auto-fills identity from BOT identity if not provided.
    - Stores compare_fields and diff_json as JSON strings.
    - Ensures UTC timestamps.
    """
    if status not in ALLOWED_STATUSES:
        # Harden by coercing to 'rejected' if unknown
        status = "rejected"

    if not (entity_code and jurisdiction_code and broker_code):
        ec, jc, bc, _ = str(get_bot_identity()).split("_")
        entity_code, jurisdiction_code, broker_code = ec, jc, bc

    db_path = _get_db_path()
    timestamp_utc = _utc_now_iso()
    if not imported_at:
        imported_at = timestamp_utc
    if not updated_at:
        updated_at = timestamp_utc

    compare_fields_json = _json_dump(compare_fields or {})
    raw_record_json = _json_dump(raw_record or {})
    json_metadata_json = _json_dump(json_metadata or {})
    diff_json = _json_dump(diff or {})

    with sqlite3.connect(db_path) as conn:
        conn.execute(RECON_TABLE_SCHEMA)  # ensure table exists
        for ddl in RECON_INDEXES:
            conn.execute(ddl)
        conn.execute(
            """
            INSERT INTO reconciliation_log (
                trade_id, group_id, entity_code, jurisdiction_code, broker_code, broker, error_code,
                account_id, statement_date, ledger_balance, ledger_entry_id, broker_balance, delta,
                status, resolution, resolved_by, resolved_at, raw_record, notes, recon_type,
                raw_record_json, compare_fields, diff_json, json_metadata, timestamp_utc, sync_run_id, api_hash,
                imported_at, updated_at, user_action, mapping_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                group_id,
                entity_code,
                jurisdiction_code,
                broker_code,
                broker,
                error_code,
                account_id,
                statement_date,
                ledger_balance,
                ledger_entry_id,
                broker_balance,
                delta,
                status,
                resolution,
                resolved_by,
                resolved_at,
                raw_record_text,
                notes,
                recon_type,
                raw_record_json,
                compare_fields_json,
                diff_json,
                json_metadata_json,
                timestamp_utc,
                sync_run_id,
                api_hash,
                imported_at,
                updated_at,
                user_action,
                mapping_version,
            ),
        )
        conn.commit()

def get_reconciliation_entries(
    sync_run_id: Optional[str] = None,
    trade_id: Optional[str] = None,
    status: Optional[str] = None,
    group_id: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Read entries with optional filters; stable order by timestamp_utc, id.
    """
    db_path = _get_db_path()
    where = []
    params: List[Any] = []
    if sync_run_id:
        where.append("sync_run_id = ?")
        params.append(sync_run_id)
    if trade_id:
        where.append("trade_id = ?")
        params.append(trade_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if group_id:
        where.append("group_id = ?")
        params.append(group_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT *
          FROM reconciliation_log
          {clause}
         ORDER BY timestamp_utc DESC, id DESC
         LIMIT ? OFFSET ?
    """
    params += [int(limit), int(offset)]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

def export_diffs_by_window(
    start_utc: str,
    end_utc: str,
    *,
    sync_run_id: Optional[str] = None,
    group_id: Optional[str] = None,
) -> str:
    """
    Export diffs (as JSON array string) for entries within [start_utc, end_utc].
    Filters may include sync_run_id and/or group_id.
    """
    db_path = _get_db_path()
    where = ["timestamp_utc >= ?", "timestamp_utc <= ?"]
    params: List[Any] = [start_utc, end_utc]
    if sync_run_id:
        where.append("sync_run_id = ?")
        params.append(sync_run_id)
    if group_id:
        where.append("group_id = ?")
        params.append(group_id)
    clause = "WHERE " + " AND ".join(where)
    sql = f"""
        SELECT id, trade_id, group_id, status, sync_run_id, mapping_version,
               timestamp_utc, compare_fields, diff_json, notes
          FROM reconciliation_log
          {clause}
         ORDER BY timestamp_utc ASC, id ASC
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, tuple(params)).fetchall()
        # Prepare clean JSON with parsed diffs where possible
        out = []
        for r in rows:
            item = dict(r)
            # Attempt to parse JSON fields for convenience
            for key in ("compare_fields", "diff_json"):
                try:
                    item[key] = json.loads(item.get(key) or "{}")
                except Exception:
                    pass
            out.append(item)
        return json.dumps(out, ensure_ascii=False, indent=2)

def snapshot_reconciliation_log() -> str:
    """
    Full JSON dump (diagnostic).
    """
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM reconciliation_log ORDER BY id ASC").fetchall()
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)
