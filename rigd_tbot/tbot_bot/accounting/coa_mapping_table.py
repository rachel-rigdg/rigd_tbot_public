# tbot_bot/accounting/coa_mapping_table.py
# COA mapping table for broker ledger sync: persistent, versioned, and auto-extending.
# Stores mapping rules for broker transaction types to bot COA accounts.
# All edits are append-only; each mapping change creates a new snapshot/version for audit/rollback.

import os
import json
from datetime import datetime
from pathlib import Path
import shutil
from tbot_bot.support.path_resolver import resolve_coa_mapping_json_path, resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

# --- Paths ---
def _get_mapping_path():
    entity_code, jurisdiction_code, broker_code, bot_id = get_bot_identity().split("_")
    return resolve_coa_mapping_json_path(entity_code, jurisdiction_code, broker_code, bot_id)

def _get_versions_dir():
    mapping_path = _get_mapping_path()
    return mapping_path.parent / "coa_mapping_versions"

# --- Core CRUD ---
def load_mapping_table():
    """
    Loads the current mapping table (JSON). If missing, creates new empty table.
    """
    path = _get_mapping_path()
    if not path.exists():
        table = {"mappings": [], "version": 1, "history": []}
        save_mapping_table(table)
        return table
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_mapping_table(table):
    """
    Writes the mapping table (JSON) to persistent storage. Creates a version snapshot.
    """
    path = _get_mapping_path()
    os.makedirs(path.parent, exist_ok=True)
    # Version and timestamp
    now = datetime.utcnow().isoformat()
    table["version"] = table.get("version", 1) + 1
    table.setdefault("history", []).append({
        "timestamp_utc": now,
        "version": table["version"],
        "user": table.get("last_updated_by", "system"),
        "reason": table.get("change_reason", "update"),
        "snapshot": table.get("mappings", [])
    })
    # Write file
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)
    # Save versioned backup
    versions_dir = _get_versions_dir()
    os.makedirs(versions_dir, exist_ok=True)
    version_file = versions_dir / f"coa_mapping_table_v{table['version']}_{now.replace(':','-')}.json"
    with open(version_file, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)

def assign_mapping(mapping_rule, user, reason=None):
    """
    Assign or update a mapping rule; rule is a dict containing broker fields and COA account.
    """
    table = load_mapping_table()
    # Remove prior mapping with same keys
    table["mappings"] = [m for m in table["mappings"]
                         if not all(m.get(k) == mapping_rule.get(k) for k in ("broker", "type", "subtype", "description"))]
    mapping_rule["updated_by"] = user
    mapping_rule["updated_at"] = datetime.utcnow().isoformat()
    table["mappings"].append(mapping_rule)
    table["last_updated_by"] = user
    table["change_reason"] = reason or "manual assignment"
    save_mapping_table(table)

def get_mapping_for_transaction(txn):
    """
    Look up the COA mapping for a transaction dict (broker/type/subtype/description).
    Returns mapping rule dict or None.
    """
    table = load_mapping_table()
    for rule in table["mappings"]:
        if all(
            rule.get(k) == txn.get(k)
            for k in ("broker", "type", "subtype", "description")
            if rule.get(k) is not None
        ):
            return rule
    return None

def flag_unmapped_transaction(txn, user="system"):
    """
    Adds a flagged, unmapped transaction for review (used by sync/reconcile).
    """
    table = load_mapping_table()
    table.setdefault("unmapped", []).append({
        "transaction": txn,
        "flagged_at": datetime.utcnow().isoformat(),
        "flagged_by": user
    })
    save_mapping_table(table)

def rollback_mapping_version(version):
    """
    Rollback to a previous mapping version (by version number).
    """
    versions_dir = _get_versions_dir()
    for f in sorted(os.listdir(versions_dir), reverse=True):
        if f.startswith(f"coa_mapping_table_v{version}_"):
            path = versions_dir / f
            with open(path, "r", encoding="utf-8") as fsrc:
                snapshot = json.load(fsrc)
            save_mapping_table(snapshot)
            return True
    return False

def export_mapping_table():
    """
    Export current mapping table as JSON.
    """
    return json.dumps(load_mapping_table(), indent=2)

def import_mapping_table(json_data, user="import"):
    """
    Import a mapping table from JSON data (full replacement).
    """
    table = json.loads(json_data)
    table["last_updated_by"] = user
    table["change_reason"] = "imported"
    save_mapping_table(table)
