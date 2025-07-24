# tbot_bot/accounting/reconciliation_log.py
# Reconciliation log table/model for broker ledger sync and reconciliation system.
# Records: trade_id, status, compare_fields, sync_run_id, timestamp_utc, api_hash, mapping_version, and related metadata.
# All changes are append-only. No deletions or overwrites.

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

RECON_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    status TEXT NOT NULL, -- ok, mismatch, local-only, broker-only, resolved
    compare_fields TEXT,  -- JSON summary of compared fields/diffs
    sync_run_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    api_hash TEXT, -- hash of the broker API record for provenance
    mapping_version TEXT, -- optional, for mapping rule snapshot/version
    broker TEXT NOT NULL,
    raw_record_json TEXT,
    notes TEXT
);
"""

def _get_db_path():
    entity_code, jurisdiction_code, broker_code, bot_id = get_bot_identity().split("_")
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)

def init_reconciliation_log_table():
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(RECON_TABLE_SCHEMA)
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
    notes=None
):
    """
    Append a reconciliation log entry. compare_fields and raw_record are JSON-serializable dicts.
    """
    db_path = _get_db_path()
    timestamp_utc = datetime.utcnow().isoformat()
    compare_fields_json = json.dumps(compare_fields or {})
    raw_record_json = json.dumps(raw_record or {})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO reconciliation_log (trade_id, status, compare_fields, sync_run_id, timestamp_utc, api_hash, mapping_version, broker, raw_record_json, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trade_id,
                status,
                compare_fields_json,
                sync_run_id,
                timestamp_utc,
                api_hash,
                mapping_version or "",
                broker,
                raw_record_json,
                notes or ""
            )
        )
        conn.commit()

def get_reconciliation_entries(sync_run_id=None, trade_id=None, status=None):
    """
    Fetch reconciliation log entries. Supports filtering by sync_run_id, trade_id, or status.
    Returns a list of dicts.
    """
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
    """
    Export all reconciliation log entries as JSON (for audit/export/backup).
    """
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM reconciliation_log")
        return json.dumps([dict(row) for row in cursor.fetchall()], indent=2)
