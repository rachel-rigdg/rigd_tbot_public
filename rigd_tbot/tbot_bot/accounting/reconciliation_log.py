# tbot_bot/accounting/reconciliation_log.py
# Reconciliation log table/model for broker ledger sync and reconciliation system.
# Records all reconciliation log fields per full spec. All changes are append-only. No deletions or overwrites.

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

# ---- Event constants (enforced non-null) ----
EVENT_UNKNOWN = "UNKNOWN"
EVENT_COA_LEG_REASSIGNED = "COA_LEG_REASSIGNED"
EVENT_COA_MAPPING_UPDATED = "COA_MAPPING_UPDATED"
EVENT_LEDGER_SYNC = "LEDGER_SYNC"
EVENT_LEDGER_SNAPSHOT = "LEDGER_SNAPSHOT"

RECON_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT,
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
    status TEXT CHECK(status IN ('pending', 'matched', 'mismatched', 'resolved')),
    event_type TEXT NOT NULL,
    resolution TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    raw_record TEXT,
    notes TEXT,
    recon_type TEXT,
    raw_record_json TEXT DEFAULT '{}',
    compare_fields TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}',
    timestamp_utc TEXT,
    sync_run_id TEXT,
    api_hash TEXT,
    imported_at TEXT,
    updated_at TEXT,
    user_action TEXT,
    mapping_version TEXT
);
"""

def _get_db_path():
    entity_code, jurisdiction_code, broker_code, bot_id = get_bot_identity().split("_")
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        return column in cols
    except Exception:
        return False

def _ensure_event_type_column(conn: sqlite3.Connection):
    """
    Migration: add event_type column if missing (cannot add NOT NULL without default in SQLite).
    Enforce non-null at write-time in code; set existing NULLs to EVENT_UNKNOWN.
    """
    if not _column_exists(conn, "reconciliation_log", "event_type"):
        conn.execute("ALTER TABLE reconciliation_log ADD COLUMN event_type TEXT")
        conn.execute("UPDATE reconciliation_log SET event_type = ? WHERE event_type IS NULL OR event_type = ''", (EVENT_UNKNOWN,))

def init_reconciliation_log_table():
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(RECON_TABLE_SCHEMA)
        _ensure_event_type_column(conn)
        conn.commit()

def log_reconciliation_entry(
    trade_id,
    status,
    compare_fields,
    sync_run_id,
    api_hash,
    broker,
    raw_record,
    mapping_version=None,
    notes=None,
    entity_code=None,
    jurisdiction_code=None,
    broker_code=None,
    error_code=None,
    account_id=None,
    statement_date=None,
    ledger_balance=None,
    ledger_entry_id=None,
    broker_balance=None,
    delta=None,
    resolution=None,
    resolved_by=None,
    resolved_at=None,
    raw_record_text=None,
    recon_type=None,
    json_metadata=None,
    imported_at=None,
    updated_at=None,
    user_action=None,
    *,
    event_type: str = EVENT_UNKNOWN,
):
    """
    Append a reconciliation log entry. Autofill codes from bot_identity if not provided.
    Enforces non-null event_type (defaults to EVENT_UNKNOWN).
    """
    if not (entity_code and jurisdiction_code and broker_code):
        identity = get_bot_identity()
        entity_code, jurisdiction_code, broker_code, _ = identity.split("_")
    db_path = _get_db_path()
    timestamp_utc = datetime.utcnow().isoformat()

    # Enforce non-null/blank event_type
    safe_event = (event_type or "").strip() or EVENT_UNKNOWN

    def make_json_safe(obj):
        if isinstance(obj, tuple):
            return [make_json_safe(i) for i in obj]
        elif isinstance(obj, dict):
            return {k: make_json_safe(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [make_json_safe(i) for i in obj]
        else:
            return obj

    compare_fields_json = json.dumps(make_json_safe(compare_fields or {}))
    raw_record_json = json.dumps(make_json_safe(raw_record or {}))
    json_metadata_json = json.dumps(json_metadata or {})

    with sqlite3.connect(db_path) as conn:
        conn.execute(RECON_TABLE_SCHEMA)  # ensure table exists on first call
        _ensure_event_type_column(conn)
        conn.execute(
            """
            INSERT INTO reconciliation_log (
                trade_id, entity_code, jurisdiction_code, broker_code, broker, error_code,
                account_id, statement_date, ledger_balance, ledger_entry_id, broker_balance, delta,
                status, event_type, resolution, resolved_by, resolved_at, raw_record, notes, recon_type,
                raw_record_json, compare_fields, json_metadata, timestamp_utc, sync_run_id, api_hash,
                imported_at, updated_at, user_action, mapping_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
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
                safe_event,
                resolution,
                resolved_by,
                resolved_at,
                raw_record_text,
                notes,
                recon_type,
                raw_record_json,
                compare_fields_json,
                json_metadata_json,
                timestamp_utc,
                sync_run_id,
                api_hash,
                imported_at,
                updated_at,
                user_action,
                mapping_version,
            )
        )
        conn.commit()

def get_reconciliation_entries(sync_run_id=None, trade_id=None, status=None):
    db_path = _get_db_path()
    query = "SELECT * FROM reconciliation_log WHERE 1=1"
    params = []
    if sync_run_id:
        query += " AND sync_run_id = ?"
        params.append(sync_run_id)
    if trade_id:
        query += " AND trade_id = ?"
        params.append(trade_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]

def snapshot_reconciliation_log():
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM reconciliation_log")
        return json.dumps([dict(row) for row in cursor.fetchall()], indent=2)

def ensure_reconciliation_log_initialized():
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(RECON_TABLE_SCHEMA)
        _ensure_event_type_column(conn)
        conn.commit()

# ---- Helper wrappers for common events ----
def log_event_coa_leg_reassigned(**kwargs):
    kwargs.setdefault("event_type", EVENT_COA_LEG_REASSIGNED)
    return log_reconciliation_entry(**kwargs)

def log_event_coa_mapping_updated(**kwargs):
    kwargs.setdefault("event_type", EVENT_COA_MAPPING_UPDATED)
    return log_reconciliation_entry(**kwargs)
