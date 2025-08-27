# tbot_bot/accounting/coa_mapping_table.py
# COA mapping table for broker ledger sync: persistent, versioned, and auto-extending.
# Stores mapping rules for broker transaction types to bot COA accounts.
# All edits are append-only; each mapping change creates a new snapshot/version for audit/rollback.

import os
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Dict, Any, List, Optional, Tuple

from tbot_bot.support.path_resolver import (
    resolve_coa_mapping_json_path,
    resolve_ledger_db_path,  # retained for compatibility
    resolve_coa_json_path,   # for validation of COA codes
)
from tbot_bot.support.utils_identity import get_bot_identity

# ----------------------------------------------------------------------
# Internal path helpers
# ----------------------------------------------------------------------
def _get_mapping_path(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None) -> Path:
    if not (entity_code and jurisdiction_code and broker_code and bot_id):
        entity_code, jurisdiction_code, broker_code, bot_id = get_bot_identity().split("_")
    return resolve_coa_mapping_json_path(entity_code, jurisdiction_code, broker_code, bot_id)

def _get_versions_dir(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None) -> Path:
    mapping_path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    return mapping_path.parent / "coa_mapping_versions"


# ----------------------------------------------------------------------
# Table load/save with version snapshots
# ----------------------------------------------------------------------
def _ensure_core_metadata(table: Dict[str, Any]) -> None:
    if "coa_version" not in table:
        table["coa_version"] = "v1.0.0"
    if any(k not in table for k in ("entity_code", "jurisdiction_code", "broker_code")):
        ec, jc, bc, bid = get_bot_identity().split("_")
        table["entity_code"] = table.get("entity_code", ec)
        table["jurisdiction_code"] = table.get("jurisdiction_code", jc)
        table["broker_code"] = table.get("broker_code", bc)
    # Ensure new "rules" bucket exists (programmatic rule_key -> account_code)
    table.setdefault("rules", [])
    # Legacy bucket (field-based mappings) stays as-is
    table.setdefault("mappings", [])
    table.setdefault("history", [])
    # For convenience
    table.setdefault("version", 1)

def load_mapping_table(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None) -> Dict[str, Any]:
    """
    Loads the current mapping table (JSON). If missing, creates new empty table.
    """
    path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    if not path.exists():
        table = {"mappings": [], "rules": [], "version": 1, "history": [], "coa_version": "v1.0.0"}
        _ensure_core_metadata(table)
        save_mapping_table(table, entity_code, jurisdiction_code, broker_code, bot_id, reason="init")
        return table
    with open(path, "r", encoding="utf-8") as f:
        table = json.load(f)
    _ensure_core_metadata(table)
    return table

def save_mapping_table(
    table: Dict[str, Any],
    entity_code=None,
    jurisdiction_code=None,
    broker_code=None,
    bot_id=None,
    reason: str = "update",
    actor: str = "system",
) -> str:
    """
    Writes the mapping table (JSON) to persistent storage. Creates a version snapshot.

    Returns:
      version_id (e.g., "v12_2025-08-27T07-20-00Z")
    """
    _ensure_core_metadata(table)
    path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    os.makedirs(path.parent, exist_ok=True)

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_iso = now.isoformat()
    table["version"] = int(table.get("version", 1)) + 1
    table["last_updated_by"] = actor
    table["change_reason"] = reason

    # Append structured history snapshot (both legacy mappings and new rules)
    history_entry = {
        "timestamp_utc": now_iso,
        "version": table["version"],
        "user": actor,
        "reason": reason,
        "snapshot": {
            "mappings": table.get("mappings", []),
            "rules": table.get("rules", []),
            "coa_version": table.get("coa_version"),
        },
    }
    table.setdefault("history", []).append(history_entry)

    # Write file
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)

    # Write versioned snapshot file
    versions_dir = _get_versions_dir(entity_code, jurisdiction_code, broker_code, bot_id)
    os.makedirs(versions_dir, exist_ok=True)
    safe_ts = now_iso.replace(":", "-")
    version_id = f"v{table['version']}_{safe_ts}Z"
    version_file = versions_dir / f"coa_mapping_table_{version_id}.json"
    with open(version_file, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)

    return version_id


# ----------------------------------------------------------------------
# Validation helpers
# ----------------------------------------------------------------------
def _active_coa_codes() -> set:
    """
    Read COA JSON and return set of active account codes.
    Accepts either {"accounts":[...]} or list[...] layouts.
    """
    codes = set()
    try:
        p = resolve_coa_json_path()
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        nodes = data.get("accounts") if isinstance(data, dict) else data
        def walk(arr):
            for n in arr or []:
                code = str(n.get("code") or "").strip()
                active = n.get("active", True)
                if code and active:
                    codes.add(code)
                kids = n.get("children") or []
                if kids:
                    walk(kids)
        walk(nodes or [])
    except Exception:
        # If COA unavailable, allow empty set and let callers decide.
        pass
    return codes

def _derive_rule_key_from_context(context_meta: Dict[str, Any]) -> str:
    """
    Stable, lowercase, pipe-delimited key:
      broker_code | trn_type | symbol-or-memo | strategy (omitted if empty)
    """
    def norm(x):
        s = ("" if x is None else str(x)).strip().lower()
        return s.replace("|", "/")
    broker = norm(context_meta.get("broker") or context_meta.get("broker_code"))
    trn = norm(context_meta.get("trn_type") or context_meta.get("type") or context_meta.get("txn_type") or context_meta.get("action"))
    symbol = norm(context_meta.get("symbol"))
    memo = norm(context_meta.get("memo") or context_meta.get("description") or context_meta.get("note") or context_meta.get("notes"))
    sym_or_memo = symbol or memo
    strat = norm(context_meta.get("strategy"))
    parts = [p for p in (broker, trn, sym_or_memo, strat) if p]
    return "|".join(parts)


# ----------------------------------------------------------------------
# Programmatic API (NEW): upsert_rule
# ----------------------------------------------------------------------
def upsert_rule(rule_key: str, account_code: str, context_meta: Optional[Dict[str, Any]], actor: str) -> str:
    """
    Create or update a programmatic mapping rule.

    Args:
      rule_key: stable key (see mapping_auto_update); if empty, derived from context_meta.
      account_code: COA account code to map to (must be active in COA).
      context_meta: arbitrary metadata used for derivation/audit (e.g., broker_code, trn_type, symbol, memo, strategy).
      actor: user id/name responsible for the change.

    Behavior:
      - Validates inputs (non-empty account_code; active COA code).
      - Inserts/updates a rule in table['rules'] keyed by 'rule_key'.
      - Persists to coa_mapping_table.json with a version bump and history snapshot.
      - Returns version_id (string) of the saved snapshot.
    """
    rule_key = (rule_key or "").strip()
    context_meta = context_meta or {}
    if not rule_key:
        rule_key = _derive_rule_key_from_context(context_meta)
    if not account_code or not isinstance(account_code, str):
        raise ValueError("account_code is required")
    active = _active_coa_codes()
    if active and account_code not in active:
        raise ValueError(f"account_code '{account_code}' is not active in COA")

    table = load_mapping_table()
    rules: List[Dict[str, Any]] = table.get("rules", [])
    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

    # Upsert by rule_key
    updated = False
    for r in rules:
        if r.get("rule_key") == rule_key:
            r["account_code"] = account_code
            # Merge/refresh context metadata (non-destructive)
            cm = dict(r.get("context_meta") or {})
            cm.update({k: v for k, v in (context_meta or {}).items() if v not in (None, "")})
            r["context_meta"] = cm
            r["updated_by"] = actor or "system"
            r["updated_at_utc"] = now_iso
            updated = True
            break
    if not updated:
        rules.append({
            "rule_key": rule_key,
            "account_code": account_code,
            "context_meta": context_meta or {},
            "created_by": actor or "system",
            "created_at_utc": now_iso,
            "updated_by": actor or "system",
            "updated_at_utc": now_iso,
        })
    table["rules"] = rules
    table["last_updated_by"] = actor or "system"
    table["change_reason"] = (context_meta.get("source") if isinstance(context_meta, dict) else None) or "upsert_rule"

    # Persist + version
    version_id = save_mapping_table(table, reason=table["change_reason"], actor=table["last_updated_by"])
    return version_id


# ----------------------------------------------------------------------
# Legacy APIs (retained)
# ----------------------------------------------------------------------
def save_mapping_table_legacy_snapshot_only(table, entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None):
    """
    DEPRECATED: kept for backward compatibility if external callers depended on old signature.
    Routes to save_mapping_table with default reason.
    """
    return save_mapping_table(table, entity_code, jurisdiction_code, broker_code, bot_id)

def assign_mapping(mapping_rule, user, reason=None):
    """
    Assign or update a field-based mapping rule; rule is a dict containing broker fields and COA account.
    """
    table = load_mapping_table()
    # Remove prior mapping with same keys
    table["mappings"] = [
        m for m in table["mappings"]
        if not all(m.get(k) == mapping_rule.get(k) for k in ("broker", "type", "subtype", "description"))
    ]
    mapping_rule["updated_by"] = user
    mapping_rule["updated_at"] = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    table["mappings"].append(mapping_rule)
    table["last_updated_by"] = user
    table["change_reason"] = reason or "manual assignment"
    save_mapping_table(table, reason=table["change_reason"], actor=user)

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
    # Optionally support programmatic rules via derived key
    # (returns a simplified view if matched)
    key = _derive_rule_key_from_context(txn or {})
    for r in mapping_table.get("rules", []):
        if r.get("rule_key") == key:
            return {"broker": txn.get("broker"), "type": txn.get("type"), "coa_account": r.get("account_code"), "rule_key": key}
    return None

def flag_unmapped_transaction(txn, user="system"):
    """
    Adds a flagged, unmapped transaction for review (used by sync/reconcile).
    """
    table = load_mapping_table()
    table.setdefault("unmapped", []).append({
        "transaction": txn,
        "flagged_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "flagged_by": user
    })
    save_mapping_table(table, reason="flag_unmapped", actor=user)

def rollback_mapping_version(version):
    """
    Rollback to a previous mapping version (by version number).
    """
    versions_dir = _get_versions_dir()
    if not versions_dir.exists():
        return False
    for fname in sorted(os.listdir(versions_dir), reverse=True):
        if fname.startswith(f"coa_mapping_table_v{version}_") or fname.startswith(f"coa_mapping_table_v{version}_".replace("v", "v")):
            path = versions_dir / fname
            with open(path, "r", encoding="utf-8") as fsrc:
                snapshot = json.load(fsrc)
            save_mapping_table(snapshot, reason="rollback", actor="system")
            return True
    return False

def export_mapping_table():
    """
    Export current mapping table as JSON with required metadata.
    """
    table = load_mapping_table()
    _ensure_core_metadata(table)
    return json.dumps(table, indent=2)

def import_mapping_table(json_data, user="import"):
    """
    Import a mapping table from JSON data (full replacement).
    """
    table = json.loads(json_data)
    _ensure_core_metadata(table)
    table["last_updated_by"] = user
    table["change_reason"] = "imported"
    save_mapping_table(table, reason="imported", actor=user)

def apply_mapping_rule(entry, mapping_table=None):
    """
    Returns two OFX/ledger-normalized dicts representing debit and credit double-entry for the provided entry.
    Mapping table is used to select COA account codes and assign side='debit' or 'credit'.
    """
    if mapping_table is None:
        mapping_table = load_mapping_table()
    mapping = get_mapping_for_transaction(entry, mapping_table)
    debit_entry = entry.copy()
    credit_entry = entry.copy()
    debit_entry["account"] = mapping["debit_account"] if mapping and "debit_account" in mapping else "Uncategorized:Debit"
    credit_entry["account"] = mapping["credit_account"] if mapping and "credit_account" in mapping else "Uncategorized:Credit"
    debit_entry["total_value"] = abs(float(debit_entry.get("total_value", 0)))
    credit_entry["total_value"] = -abs(float(credit_entry.get("total_value", 0)))
    debit_entry["side"] = "debit"
    credit_entry["side"] = "credit"
    return debit_entry, credit_entry
