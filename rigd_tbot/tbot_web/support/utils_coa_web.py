# tbot_web/support/utils_coa_web.py
# Loads, validates, and manages the bot’s Chart of Accounts (COA); interfaces with tbot_ledger_coa_template.json and provides COA to other modules

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# Paths (must be resolved via path_resolver in production)
from tbot_bot.support.path_resolver import (
    resolve_coa_json_path,
    resolve_coa_metadata_path,
    resolve_coa_audit_log_path,
)

# --- Load COA metadata and accounts ---
def load_coa_metadata_and_accounts() -> Dict[str, Any]:
    coa_json_path = resolve_coa_json_path()
    if not os.path.exists(coa_json_path):
        raise FileNotFoundError("COA file not found.")
    with open(coa_json_path, "r", encoding="utf-8") as cf:
        accounts = json.load(cf)
    # --- ADD FLAT ACCOUNTS LOGIC ---
    def flatten_coa_accounts(accounts, depth=0, out=None):
        if out is None:
            out = []
        for acc in accounts:
            out.append((acc["code"], acc["name"]))
            if "children" in acc and acc["children"]:
                flatten_coa_accounts(acc["children"], depth + 1, out)
        return out
    accounts_flat = flatten_coa_accounts(accounts)
    return {"accounts": accounts, "accounts_flat": accounts_flat}

# --- Save COA JSON and log change (admin) ---
def save_coa_json(new_accounts: Any, user: str, diff: str):
    coa_json_path = resolve_coa_json_path()
    coa_metadata_path = resolve_coa_metadata_path()
    audit_log_path = resolve_coa_audit_log_path()
    # Write accounts
    with open(coa_json_path, "w", encoding="utf-8") as cf:
        json.dump(new_accounts, cf, indent=2)
    # Update metadata
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    if os.path.exists(coa_metadata_path):
        with open(coa_metadata_path, "r", encoding="utf-8") as mdf:
            metadata = json.load(mdf)
    else:
        metadata = {}
    metadata["last_updated_utc"] = now
    with open(coa_metadata_path, "w", encoding="utf-8") as mdf:
        json.dump(metadata, mdf, indent=2)
    # Log audit entry
    audit_entry = {
        "timestamp_utc": now,
        "user": user,
        "summary": f"COA updated by {user}",
        "diff": diff,
    }
    try:
        with open(audit_log_path, "r", encoding="utf-8") as alf:
            history = json.load(alf)
    except Exception:
        history = []
    history.insert(0, audit_entry)
    history = history[:100]
    with open(audit_log_path, "w", encoding="utf-8") as alf:
        json.dump(history, alf, indent=2)

# --- Export as Markdown ---
def export_coa_markdown(coa_data: Dict[str, Any]) -> str:
    out = []
    meta = coa_data.get("metadata", {})
    out.append(f"# Chart of Accounts (COA) — {meta.get('entity_code','')}/{meta.get('jurisdiction_code','')} v{meta.get('coa_version','')}")
    out.append(f"**Currency:** {meta.get('currency_code','')}\n")
    out.append(f"**COA Version:** {meta.get('coa_version','')}")
    out.append(f"**Created:** {meta.get('created_at_utc','')}")
    out.append(f"**Last Updated:** {meta.get('last_updated_utc','')}\n")
    def walk(accs, depth=0):
        for acc in accs:
            out.append(f"{'  '*depth}- **{acc['code']}**: {acc['name']}")
            if acc.get("children"):
                walk(acc["children"], depth+1)
    walk(coa_data["accounts"])
    return "\n".join(out)

# --- Export as CSV ---
def export_coa_csv(coa_data: Dict[str, Any]) -> str:
    rows = ["code,name,depth"]
    def walk(accs, depth=0):
        for acc in accs:
            rows.append(f"{acc['code']},{acc['name']},{depth}")
            if acc.get("children"):
                walk(acc["children"], depth+1)
    walk(coa_data["accounts"])
    return "\n".join(rows)

# --- Audit Log ---
def get_coa_audit_log(limit: int = 50) -> List[Dict[str, Any]]:
    audit_log_path = resolve_coa_audit_log_path()
    try:
        with open(audit_log_path, "r", encoding="utf-8") as alf:
            history = json.load(alf)
    except Exception:
        history = []
    return history[:limit]

# --- Compute COA diff (for audit log) ---
def compute_coa_diff(old: Any, new: Any) -> str:
    # Shallow JSON diff — admin can expand for richer audit if needed
    old_json = json.dumps(old, indent=2, sort_keys=True)
    new_json = json.dumps(new, indent=2, sort_keys=True)
    if old_json == new_json:
        return "No changes."
    from difflib import unified_diff
    diff_lines = list(unified_diff(
        old_json.splitlines(), new_json.splitlines(),
        fromfile="old", tofile="new", lineterm=""
    ))
    if not diff_lines:
        return "No changes."
    return "\n".join(diff_lines[:200])

# --- COA structure validator ---
def validate_coa_json(accounts: Any):
    # Must be a non-empty list
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("COA accounts must be a non-empty list.")
    # Each account must have code, name, children (list or omitted)
    def check(acc):
        if "code" not in acc or "name" not in acc:
            raise ValueError("Each account must have 'code' and 'name'.")
        if "children" in acc and not isinstance(acc["children"], list):
            raise ValueError("'children' must be a list if present.")
        for c in acc.get("children", []):
            check(c)
    for acc in accounts:
        check(acc)
