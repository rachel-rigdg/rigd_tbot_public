# tbot_bot/accounting/coa_mapping_table.py
# COA mapping table for broker ledger sync: persistent, versioned, immutable rows with active flag.
# Stores mapping rules for broker transaction types to bot COA accounts.
# All edits are append-only; each change increments version_id and snapshots a full table for audit/rollback.

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from tbot_bot.support.path_resolver import resolve_coa_mapping_json_path
from tbot_bot.support.utils_identity import get_bot_identity

# ----------------------------
# Helpers / internal utilities
# ----------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _identity_tuple(
    entity_code: Optional[str],
    jurisdiction_code: Optional[str],
    broker_code: Optional[str],
    bot_id: Optional[str],
) -> Tuple[str, str, str, str]:
    if entity_code and jurisdiction_code and broker_code and bot_id:
        return entity_code, jurisdiction_code, broker_code, bot_id
    parts = str(get_bot_identity()).split("_")
    if len(parts) >= 4:
        return parts[0], parts[1], parts[2], parts[3]
    raise ValueError("Invalid bot identity; expected 'ENTITY_JURISDICTION_BROKER_BOTID'")

def _mapping_path(
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
) -> Path:
    ec, jc, bc, bid = _identity_tuple(entity_code, jurisdiction_code, broker_code, bot_id)
    return resolve_coa_mapping_json_path(ec, jc, bc, bid)

def _versions_dir(mapping_path: Path) -> Path:
    return mapping_path.parent / "coa_mapping_versions"

def _audit_path(mapping_path: Path) -> Path:
    return mapping_path.parent / "audit" / "coa_mapping_audit.jsonl"

def _atomic_write_json(path: Path, payload: dict) -> None:
    """
    Atomic JSON write: write to temp file in same dir, fsync, then replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def _write_json(path: Path, payload: dict) -> None:
    _atomic_write_json(path, payload)

def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _audit(mapping_path: Path, event: dict) -> None:
    apath = _audit_path(mapping_path)
    apath.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts_utc": _utc_now_iso(), **event}
    with apath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def _rule_code(match: Dict[str, str]) -> str:
    """Deterministic rule code from match keys (broker/type/subtype/description)."""
    broker = match.get("broker", "").strip()
    typ = match.get("type", "").strip()
    sub = match.get("subtype", "").strip()
    desc = match.get("description", "").strip()
    return ":".join([broker, typ, sub, desc])

# ----------------------------
# Data model
# ----------------------------

@dataclass(frozen=True)
class MappingRow:
    # Immutable row; create a new row to change mapping. Previous rows remain in history.
    code: str
    debit_account: str
    credit_account: str
    active: bool
    version_id: int
    updated_by: str
    updated_at_utc: str
    reason: str
    match: Dict[str, str]  # broker/type/subtype/description (any missing fields may be omitted)

# ----------------------------
# Load / Save (versioned)
# ----------------------------

def _bootstrap_table(
    mapping_path: Path,
    ec: str,
    jc: str,
    bc: str,
    bid: str,
) -> dict:
    now = _utc_now_iso()
    table = {
        "meta": {
            "entity_code": ec,
            "jurisdiction_code": jc,
            "broker_code": bc,
            "bot_id": bid,
            "created_at_utc": now,
            "updated_at_utc": now,
            "coa_version": "v1.0.0",
            "version_id": 1,
        },
        "version": 1,     # back-compat mirror
        "rows": [],
        "history": [],
        "unmapped": [],
    }
    _write_json(mapping_path, table)
    versions = _versions_dir(mapping_path)
    versions.mkdir(parents=True, exist_ok=True)
    snap_name = f"coa_mapping_v{table['meta']['version_id']}_{table['meta']['updated_at_utc'].replace(':','-')}.json"
    _write_json(versions / snap_name, table)
    _audit(mapping_path, {"event": "bootstrap", "meta": table["meta"]})
    return table

def _normalize_legacy_table(table: dict, mapping_path: Path) -> dict:
    """Migrate legacy shape with 'mappings'/'version' to new meta/rows/version_id."""
    if "meta" in table and "rows" in table:
        table["meta"].setdefault("updated_at_utc", _utc_now_iso())
        table["meta"].setdefault("coa_version", "v1.0.0")
        table["meta"].setdefault("version_id", int(table.get("version", 1)))
        table.setdefault("history", [])
        table.setdefault("unmapped", [])
        table["version"] = int(table["meta"]["version_id"])
        return table

    # Legacy → New
    now = _utc_now_iso()
    rows: List[dict] = []
    for m in table.get("mappings", []):
        match = {k: m.get(k) for k in ("broker", "type", "subtype", "description") if m.get(k) is not None}
        code = m.get("code") or _rule_code(match)
        rows.append({
            "code": code,
            "debit_account": m.get("debit_account", "Uncategorized:Debit"),
            "credit_account": m.get("credit_account", "Uncategorized:Credit"),
            "active": True,
            "version_id": table.get("version", 1),
            "updated_by": m.get("updated_by", "system"),
            "updated_at_utc": m.get("updated_at") or now,
            "reason": m.get("reason", "legacy-import"),
            "match": match,
        })

    parts = str(get_bot_identity()).split("_")
    ec = table.get("entity_code") or parts[0]
    jc = table.get("jurisdiction_code") or parts[1]
    bc = table.get("broker_code") or parts[2]
    bid = parts[3] if len(parts) >= 4 else "BOT"

    new_table = {
        "meta": {
            "entity_code": ec,
            "jurisdiction_code": jc,
            "broker_code": bc,
            "bot_id": bid,
            "created_at_utc": now,
            "updated_at_utc": now,
            "coa_version": table.get("coa_version", "v1.0.0"),
            "version_id": table.get("version", 1),
        },
        "version": int(table.get("version", 1)),
        "rows": rows,
        "history": table.get("history", []),
        "unmapped": table.get("unmapped", []),
    }
    _audit(mapping_path, {"event": "migrated_legacy_table"})
    return new_table

def load_mapping_table(
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> dict:
    """
    Load the current (or a specific version) mapping table.
    Lazy-creates the live file if missing (bootstrap).
    """
    mapping_path = _mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    if not mapping_path.exists():
        ec, jc, bc, bid = _identity_tuple(entity_code, jurisdiction_code, broker_code, bot_id)
        return _bootstrap_table(mapping_path, ec, jc, bc, bid)

    if version_id is None:
        table = _read_json(mapping_path)
        table = _normalize_legacy_table(table, mapping_path)
        table["version"] = int(table["meta"].get("version_id", 1))
        return table

    # Specific version → load snapshot
    versions = _versions_dir(mapping_path)
    if not versions.exists():
        raise FileNotFoundError("No versions directory found for COA mapping.")
    candidates = sorted([p for p in versions.glob(f"coa_mapping_v{version_id}_*.json")])
    if not candidates:
        candidates = sorted([p for p in versions.glob(f"coa_mapping_table_v{version_id}_*.json")])
    if not candidates:
        raise FileNotFoundError(f"COA mapping snapshot v{version_id} not found.")
    snap = _read_json(candidates[-1])
    snap = _normalize_legacy_table(snap, mapping_path)
    snap["version"] = int(snap["meta"].get("version_id", version_id))
    return snap

def _save_mapping_table(table: dict, mapping_path: Path, user: str, reason: str) -> dict:
    # bump version and snapshot
    table["meta"]["version_id"] = int(table["meta"].get("version_id", 0)) + 1
    table["meta"]["updated_at_utc"] = _utc_now_iso()
    table["version"] = int(table["meta"]["version_id"])
    snap_meta = {
        "version_id": table["meta"]["version_id"],
        "timestamp_utc": table["meta"]["updated_at_utc"],
        "user": user,
        "reason": reason,
        "row_count": len(table.get("rows", [])),
    }
    table.setdefault("history", []).append(snap_meta)
    _write_json(mapping_path, table)
    versions = _versions_dir(mapping_path)
    versions.mkdir(parents=True, exist_ok=True)
    snap_name = f"coa_mapping_v{table['meta']['version_id']}_{table['meta']['updated_at_utc'].replace(':','-')}.json"
    _write_json(versions / snap_name, table)
    _audit(mapping_path, {"event": "save", **snap_meta})
    return table

# Public save wrapper (manual save of an in-memory table)
def save_mapping_table(table: dict, user: str = "system", reason: str = "manual-save") -> dict:
    mp = _mapping_path(None, None, None, None)
    return _save_mapping_table(table, mp, user=user, reason=reason)

# -----------------------------------
# Public mutation / assignment APIs
# -----------------------------------

def assign_mapping(mapping_rule: Dict[str, str], user: str, reason: Optional[str] = None) -> dict:
    """
    Create/replace a mapping rule (append-only):
      mapping_rule: {broker?, type?, subtype?, description?, debit_account, credit_account, code?}
    """
    mapping_path = _mapping_path(None, None, None, None)
    table = load_mapping_table()
    match = {k: mapping_rule.get(k) for k in ("broker", "type", "subtype", "description") if mapping_rule.get(k)}
    code = mapping_rule.get("code") or _rule_code(match)

    # Deactivate prior active rows for this code
    for r in table.get("rows", []):
        if r.get("code") == code and r.get("active", False):
            r["active"] = False

    # Append new immutable row with the *next* version_id as preview
    next_version = int(table["meta"].get("version_id", 0)) + 1
    new_row = MappingRow(
        code=code,
        debit_account=mapping_rule["debit_account"],
        credit_account=mapping_rule["credit_account"],
        active=True,
        version_id=next_version,
        updated_by=user,
        updated_at_utc=_utc_now_iso(),
        reason=reason or "manual assignment",
        match=match,
    )
    table["rows"].append({**new_row.__dict__})
    table = _save_mapping_table(table, mapping_path, user=user, reason=new_row.reason)
    return table

def import_mapping_table(json_data: str, user: str = "import") -> dict:
    """
    Full replacement import (append-only by versioning; existing live file is overwritten
    but previous states remain in versions/ snapshots).
    """
    mapping_path = _mapping_path(None, None, None, None)
    incoming = json.loads(json_data)
    table = load_mapping_table()  # ensures shape
    # Normalize incoming to rows
    rows: List[dict] = []
    now = _utc_now_iso()
    next_version = int(table["meta"].get("version_id", 0)) + 1
    for m in incoming.get("rows") or incoming.get("mappings", []):
        match = m.get("match") or {k: m.get(k) for k in ("broker", "type", "subtype", "description") if m.get(k)}
        code = m.get("code") or _rule_code(match)
        rows.append({
            "code": code,
            "debit_account": m.get("debit_account", "Uncategorized:Debit"),
            "credit_account": m.get("credit_account", "Uncategorized:Credit"),
            "active": bool(m.get("active", True)),
            "version_id": next_version,
            "updated_by": m.get("updated_by", user),
            "updated_at_utc": m.get("updated_at_utc", now),
            "reason": m.get("reason", "imported"),
            "match": match,
        })
    table["rows"] = rows
    table["meta"]["coa_version"] = incoming.get("coa_version", table["meta"].get("coa_version", "v1.0.0"))
    table = _save_mapping_table(table, mapping_path, user=user, reason="imported mapping")
    return table

# -----------------------------------
# Public read/query APIs
# -----------------------------------

def get_version(
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
) -> int:
    table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)
    return int(table["meta"]["version_id"])

def get_accounts_for(
    code: str,
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> Optional[Tuple[str, str]]:
    table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id, version_id)
    rows = [r for r in table.get("rows", []) if r.get("code") == code and r.get("active", False)]
    if not rows:
        return None
    rows.sort(key=lambda r: int(r.get("version_id", 0)))
    r = rows[-1]
    return r.get("debit_account"), r.get("credit_account")

def get_mapping_for_transaction(
    txn: Dict[str, str],
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> Optional[dict]:
    """
    Look up the active COA mapping row for a transaction dict (broker/type/subtype/description).
    Returns a MappingRow (as dict) or None.
    """
    table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id, version_id)
    want = {k: txn.get(k) for k in ("broker", "type", "subtype", "description") if txn.get(k) is not None}
    code = txn.get("code") or _rule_code(want)
    # Prefer explicit code match on active rows; fall back to exact match dict
    candidates = [r for r in table.get("rows", []) if r.get("code") == code and r.get("active", False)]
    if candidates:
        candidates.sort(key=lambda r: int(r.get("version_id", 0)))
        return candidates[-1]
    # Fallback by exact match
    for r in sorted(table.get("rows", []), key=lambda x: int(x.get("version_id", 0))):
        if not r.get("active", False):
            continue
        m = r.get("match", {})
        if all(m.get(k) == want.get(k) for k in want.keys()):
            return r
    return None

def apply_mapping_rule(
    entry: Dict[str, str],
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> Tuple[dict, dict]:
    """
    Returns two OFX/ledger-normalized dicts representing debit and credit splits for provided entry.
    """
    mapping = get_mapping_for_transaction(entry, entity_code, jurisdiction_code, broker_code, bot_id, version_id)
    debit_entry = dict(entry)
    credit_entry = dict(entry)

    da = (mapping or {}).get("debit_account", "Uncategorized:Debit")
    ca = (mapping or {}).get("credit_account", "Uncategorized:Credit")
    amount = float(entry.get("total_value", 0.0))
    if amount < 0:
        amount = -amount  # normalize magnitude; sign handled by side

    debit_entry["account"] = da
    credit_entry["account"] = ca
    debit_entry["total_value"] = amount
    credit_entry["total_value"] = -amount
    debit_entry["side"] = "debit"
    credit_entry["side"] = "credit"
    return debit_entry, credit_entry

# Per spec naming
def debit_credit_for_entry(
    entry: Dict[str, str],
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> Tuple[dict, dict]:
    """
    Alias to apply_mapping_rule(); required by posting pipeline contract.
    """
    return apply_mapping_rule(entry, entity_code, jurisdiction_code, broker_code, bot_id, version_id)

def flag_unmapped_transaction(txn: Dict[str, str], user: str = "system") -> dict:
    """
    Adds a flagged, unmapped transaction for review (used by sync/reconcile).
    """
    mapping_path = _mapping_path(None, None, None, None)
    table = load_mapping_table()
    table.setdefault("unmapped", []).append({
        "transaction": txn,
        "flagged_at_utc": _utc_now_iso(),
        "flagged_by": user,
    })
    _audit(mapping_path, {"event": "flag_unmapped", "user": user, "txn": txn})
    return _save_mapping_table(table, mapping_path, user=user, reason="unmapped_txn")

def ensure_required(
    required_codes: Optional[Iterable[str]] = None,
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> None:
    """
    Ensure that mapping uses the required COA account codes.
    Supports prefixes using 'x' wildcard, e.g., '111x' → any account starting with '111'.
    Raises ValueError if any requirement is missing.
    """
    req = list(required_codes) if required_codes else ["111x", "103x", "1120", "1130", "4080", "4090"]
    table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id, version_id)
    accounts: List[str] = []
    for r in table.get("rows", []):
        if not r.get("active", False):
            continue
        da = str(r.get("debit_account", ""))
        ca = str(r.get("credit_account", ""))
        if da:
            accounts.append(da)
        if ca:
            accounts.append(ca)

    missing: List[str] = []
    for needle in req:
        if needle.endswith("x"):
            prefix = needle[:-1]
            found = any(a.startswith(prefix) for a in accounts)
        else:
            found = any(a.startswith(needle) for a in accounts)
        if not found:
            missing.append(needle)

    if missing:
        raise ValueError(f"Required COA codes missing from mapping: {', '.join(missing)}")

def export_mapping_table(
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> str:
    """
    Export mapping table JSON (for external audit/backup).
    """
    table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id, version_id)
    return json.dumps(table, indent=2, ensure_ascii=False)

def rollback_mapping_version(
    version_id: int,
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
) -> bool:
    """
    Rollback live table to a previous snapshot by version_id.
    """
    mapping_path = _mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    snap = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id, version_id=version_id)
    _write_json(mapping_path, snap)  # overwrite live with snapshot
    snap["version"] = int(snap["meta"].get("version_id", version_id))
    _audit(mapping_path, {"event": "rollback_requested", "to_version": version_id})
    _save_mapping_table(snap, mapping_path, user="system", reason=f"rollback to v{version_id}")
    return True
