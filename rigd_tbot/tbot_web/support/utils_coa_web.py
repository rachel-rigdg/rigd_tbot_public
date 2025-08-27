# tbot_web/support/utils_coa_web.py
# Loads, validates, and manages the bot’s Chart of Accounts (COA); interfaces with tbot_ledger_coa_template.json and provides COA to other modules

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

# Paths (must be resolved via path_resolver in production)
from tbot_bot.support.path_resolver import (
    resolve_coa_json_path,
    resolve_coa_metadata_path,
    resolve_coa_audit_log_path,
)

# Optional mapping helpers for rule resolution
try:
    from tbot_bot.accounting.coa_mapping_table import load_mapping_table, get_mapping_for_transaction
except Exception:  # pragma: no cover
    load_mapping_table = None  # type: ignore
    get_mapping_for_transaction = None  # type: ignore


# --- Load COA metadata and accounts ---
def load_coa_metadata_and_accounts() -> Dict[str, Any]:
    """
    Returns:
      {
        "accounts": <hierarchical list>,
        "accounts_flat": List[Tuple[code, name]],                 # backwards compatible
        "accounts_flat_dropdown": List[Tuple[code, label]],       # active only; label = "Name — Path"
      }
    """
    coa_json_path = resolve_coa_json_path()
    if not os.path.exists(coa_json_path):
        raise FileNotFoundError("COA file not found.")
    with open(coa_json_path, "r", encoding="utf-8") as cf:
        accounts = json.load(cf)

    flat_all = _flatten_coa_accounts(accounts, include_inactive=True)
    accounts_flat: List[Tuple[str, str]] = [(a["code"], a["name"]) for a in flat_all]

    flat_active = [a for a in flat_all if a.get("active", True)]
    # Dropdown label favors clarity: "Name — Path" (without repeating code in path)
    accounts_flat_dropdown: List[Tuple[str, str]] = [
        (a["code"], f'{a["name"]} — {a["path"]}') for a in flat_active
    ]

    return {
        "accounts": accounts,
        "accounts_flat": accounts_flat,
        "accounts_flat_dropdown": accounts_flat_dropdown,
    }


def _flatten_coa_accounts(accounts: List[Dict[str, Any]], parent_path: str = "", include_inactive: bool = False) -> List[Dict[str, Any]]:
    """
    Flattens hierarchical COA into a list of dicts:
      {"code","name","path","depth","active":bool}
    Path is colon-delimited by account names: e.g., "Assets:Brokerage:Cash"
    """
    out: List[Dict[str, Any]] = []

    def walk(accs: List[Dict[str, Any]], parent: str, depth: int):
        for acc in accs:
            name = acc.get("name", "")
            code = acc.get("code", "")
            active = acc.get("active", True)
            path = f"{parent}:{name}" if parent else name
            row = {
                "code": code,
                "name": name,
                "path": path,
                "depth": depth,
                "active": bool(active),
            }
            if include_inactive or row["active"]:
                out.append(row)
            children = acc.get("children") or []
            if isinstance(children, list) and children:
                walk(children, path, depth + 1)

    walk(accounts or [], parent_path, 0)
    return out


# --- Helper: active COA list for dropdown (code + name + path) ---
def list_active_coa_for_dropdown() -> List[Tuple[str, str]]:
    """
    Returns a list suitable for <select> options:
      [(code, "Name — Path"), ...]
    Active accounts only (acc.active != False).
    """
    data = load_coa_metadata_and_accounts()
    return data.get("accounts_flat_dropdown", [])


# --- Helper: derive stable rule key from context (for deep-linking/view rule) ---
def derive_rule_key(context: Dict[str, Any]) -> str:
    """
    Build a stable key from available transaction context.
    Preference order aligns with mapping auto-update guidance:
      broker_code | trn_type | subtype | symbol | memo/description | strategy
    Lowercased and pipe-delimited.
    """
    def norm(x: Optional[str]) -> str:
        return (str(x or "").strip().lower().replace("|", "/")) or ""

    broker = norm(context.get("broker") or context.get("broker_code"))
    trntype = norm(context.get("type") or context.get("trn_type") or context.get("txn_type"))
    subtype = norm(context.get("subtype"))
    symbol = norm(context.get("symbol"))
    memo = norm(context.get("memo") or context.get("description") or context.get("note"))
    strategy = norm(context.get("strategy"))

    parts = [p for p in (broker, trntype, subtype, symbol or memo, strategy) if p]
    return "|".join(parts) if parts else ""


# --- Resolve rule-by-context for “View Mapping Rule” ---
def resolve_mapping_rule_by_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns:
      {
        "rule_key": str,
        "rule": dict|None,           # matched mapping rule (if any)
        "link": str,                 # deep link URL to coa_mapping view for this context
      }
    """
    rule_key = derive_rule_key(context)
    rule = None

    # Try direct API if available
    if callable(get_mapping_for_transaction):
        try:
            rule = get_mapping_for_transaction(context)
        except Exception:
            rule = None
    else:
        # Fallback: scan table by simple key match if available
        try:
            tbl = load_mapping_table() if callable(load_mapping_table) else {}
            rules = (tbl.get("rules") or []) if isinstance(tbl, dict) else []
            for r in rules:
                if r.get("rule_key") == rule_key:
                    rule = r
                    break
        except Exception:
            rule = None

    # Construct a context-aware deep-link back to the mapping UI
    # Caller can append additional params (e.g., entry_id) as needed.
    link = "/coa_mapping?from=ledger"
    if rule_key:
        from urllib.parse import urlencode
        link = f"/coa_mapping?{urlencode({'from':'ledger','rule_key': rule_key})}"

    return {"rule_key": rule_key, "rule": rule, "link": link}


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
