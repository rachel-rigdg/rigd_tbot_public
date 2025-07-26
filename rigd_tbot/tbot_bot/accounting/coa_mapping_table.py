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

def _get_mapping_path(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None):
    if not (entity_code and jurisdiction_code and broker_code and bot_id):
        entity_code, jurisdiction_code, broker_code, bot_id = get_bot_identity().split("_")
    return resolve_coa_mapping_json_path(entity_code, jurisdiction_code, broker_code, bot_id)

def _get_versions_dir(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None):
    mapping_path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    return mapping_path.parent / "coa_mapping_versions"

def load_mapping_table(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None):
    """
    Loads the current mapping table (JSON). If missing, creates new empty table.
    """
    path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    if not path.exists():
        table = {"mappings": [], "version": 1, "history": [], "coa_version": "v1.0.0"}
        save_mapping_table(table, entity_code, jurisdiction_code, broker_code, bot_id)
        return table
    with open(path, "r", encoding="utf-8") as f:
        table = json.load(f)
    if "coa_version" not in table:
        table["coa_version"] = "v1.0.0"
    if "entity_code" not in table or "jurisdiction_code" not in table or "broker_code" not in table:
        # Add core metadata if missing
        ec, jc, bc, bid = get_bot_identity().split("_")
        table["entity_code"] = ec
        table["jurisdiction_code"] = jc
        table["broker_code"] = bc
    return table

def save_mapping_table(table, entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None):
    """
    Writes the mapping table (JSON) to persistent storage. Creates a version snapshot.
    """
    path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
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
    # Guarantee required metadata
    if "coa_version" not in table:
        table["coa_version"] = "v1.0.0"
    if "entity_code" not in table or "jurisdiction_code" not in table or "broker_code" not in table:
        ec, jc, bc, bid = get_bot_identity().split("_")
        table["entity_code"] = ec
        table["jurisdiction_code"] = jc
        table["broker_code"] = bc
    # Write file
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)
    versions_dir = _get_versions_dir(entity_code, jurisdiction_code, broker_code, bot_id)
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

def get_mapping_for_transaction(txn, mapping_table=None):
    """
    Look up the COA mapping for a transaction dict (broker/type/subtype/description).
    Returns mapping rule dict or None.
    """
    if mapping_table is None:
        mapping_table = load_mapping_table()
    for rule in mapping_table.get("mappings", []):
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
    Export current mapping table as JSON with required metadata.
    """
    table = load_mapping_table()
    # Guarantee metadata before export
    if "coa_version" not in table:
        table["coa_version"] = "v1.0.0"
    if "entity_code" not in table or "jurisdiction_code" not in table or "broker_code" not in table:
        ec, jc, bc, bid = get_bot_identity().split("_")
        table["entity_code"] = ec
        table["jurisdiction_code"] = jc
        table["broker_code"] = bc
    return json.dumps(table, indent=2)

def import_mapping_table(json_data, user="import"):
    """
    Import a mapping table from JSON data (full replacement).
    """
    table = json.loads(json_data)
    table["last_updated_by"] = user
    table["change_reason"] = "imported"
    if "coa_version" not in table:
        table["coa_version"] = "v1.0.0"
    if "entity_code" not in table or "jurisdiction_code" not in table or "broker_code" not in table:
        ec, jc, bc, bid = get_bot_identity().split("_")
        table["entity_code"] = ec
        table["jurisdiction_code"] = jc
        table["broker_code"] = bc
    save_mapping_table(table)

def apply_mapping_rule(entry, mapping_table=None):
    """
    Returns two OFX/ledger-normalized dicts representing debit and credit double-entry for the provided entry.
    Mapping table is used to select COA account codes.
    """
    if mapping_table is None:
        mapping_table = load_mapping_table()
    mapping = get_mapping_for_transaction(entry, mapping_table)
    debit_entry = entry.copy()
    credit_entry = entry.copy()
    # Defaults for demo: override with mapping/account codes as needed.
    debit_entry["account"] = mapping["debit_account"] if mapping and "debit_account" in mapping else "Uncategorized:Debit"
    credit_entry["account"] = mapping["credit_account"] if mapping and "credit_account" in mapping else "Uncategorized:Credit"
    # Set values for double-entry compliance
    debit_entry["total_value"] = abs(float(debit_entry.get("total_value", 0)))
    credit_entry["total_value"] = -abs(float(credit_entry.get("total_value", 0)))
    return debit_entry, credit_entry
