# tbot_web/support/utils_coa_web.py
# Loads, validates, and manages the bot’s Chart of Accounts (COA); interfaces with
# tbot_ledger_coa_template.json and provides COA to other modules. Robust to
# unprovisioned workdirs by falling back to the DB (coa_accounts) or a tiny
# built-in COA so the UI dropdowns never come up empty.

from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

# Paths (must be resolved via path_resolver in production)
from tbot_bot.support.path_resolver import (
    resolve_coa_json_path,
    resolve_coa_metadata_path,
    resolve_coa_audit_log_path,
    resolve_ledger_db_path,   # DB fallback
)
from tbot_bot.support.decrypt_secrets import load_bot_identity

# Optional mapping helpers for rule resolution
try:
    from tbot_bot.accounting.coa_mapping_table import (
        load_mapping_table,
        get_mapping_for_transaction,
    )
except Exception:  # pragma: no cover
    load_mapping_table = None  # type: ignore
    get_mapping_for_transaction = None  # type: ignore


# ---------- Internal helpers ----------

def _normalize_coa_shape(raw: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Accepts either:
      - {"metadata": {...}, "accounts": [...]}
      - [...]
    Returns (accounts_list, metadata_dict).
    """
    if isinstance(raw, dict) and "accounts" in raw:
        accounts = raw.get("accounts") or []
        meta = {k: v for k, v in raw.items() if k != "accounts"}
        return (accounts if isinstance(accounts, list) else []), meta
    if isinstance(raw, list):
        return raw, {}
    return [], {}


def _minimal_coa() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """A tiny, safe default COA used when nothing is provisioned yet."""
    accounts = [
        {"code": "1000_CASH", "name": "Cash", "children": [], "active": True},
        {"code": "3999_SUSPENSE", "name": "Suspense / Unmapped", "children": [], "active": True},
        {"code": "5000_TRADING_PNL", "name": "Trading P&L", "children": [], "active": True},
    ]
    meta = {
        "coa_version": "0",
        "currency_code": "USD",
        "created_at_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "last_updated_utc": None,
    }
    return accounts, meta


def _try_load_from_json() -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    path = resolve_coa_json_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as cf:
            raw = json.load(cf)
        accounts, meta = _normalize_coa_shape(raw)
        # Basic sanity: require code+name on the first item
        if isinstance(accounts, list) and accounts and "code" in accounts[0] and "name" in accounts[0]:
            return accounts, meta
    except Exception:
        pass
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
        ).fetchone())
    except Exception:
        return False


def _try_load_from_db() -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    """
    Fallback reader for unprovisioned environments:
    - Reads COA from ledger DB table `coa_accounts`.
    - Accepts either legacy schema with `account_json` column or newer with `code`/`name`.
    """
    try:
        entity_code, jurisdiction_code, broker_code, bot_id = (load_bot_identity() or "___").split("_", 3)
        db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    except Exception:
        return None

    if not db_path or not os.path.exists(db_path):
        return None

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "coa_accounts"):
                return None

            # Probe columns
            cols = [r[1] for r in conn.execute("PRAGMA table_info(coa_accounts)").fetchall()]
            rows: List[Dict[str, Any]] = []

            if "account_json" in cols:
                # Legacy style: parse JSON blob for code/name/children/active
                for r in conn.execute("SELECT account_json FROM coa_accounts"):
                    try:
                        obj = json.loads(r[0]) if r[0] else {}
                    except Exception:
                        obj = {}
                    code = obj.get("code")
                    name = obj.get("name")
                    if code and name:
                        rows.append({
                            "code": str(code),
                            "name": str(name),
                            "children": obj.get("children") or [],
                            "active": bool(obj.get("active", True)),
                        })
            else:
                # Direct columns, if present
                code_col = "code" if "code" in cols else None
                name_col = "name" if "name" in cols else None
                if code_col and name_col:
                    for r in conn.execute(f"SELECT {code_col} AS code, {name_col} AS name FROM coa_accounts"):
                        code = r["code"]
                        name = r["name"]
                        if code and name:
                            rows.append({
                                "code": str(code),
                                "name": str(name),
                                "children": [],
                                "active": True,
                            })

            if rows:
                # Deduplicate by code (keep first)
                seen = set()
                uniq: List[Dict[str, Any]] = []
                for a in rows:
                    c = a["code"]
                    if c not in seen:
                        seen.add(c)
                        uniq.append(a)
                meta = {
                    "source": "db_fallback",
                    "coa_version": None,
                    "currency_code": "USD",
                    "last_updated_utc": None,
                }
                return uniq, meta
    except Exception:
        return None

    return None


def _flatten_coa_accounts(accounts: List[Dict[str, Any]], parent_path: str = "", include_inactive: bool = False) -> List[Dict[str, Any]]:
    """
    Flattens hierarchical COA into a list of dicts:
      {"code","name","path","depth","active":bool}
    Path is colon-delimited by account names: e.g., "Assets:Brokerage:Cash"
    """
    out: List[Dict[str, Any]] = []

    def walk(accs: List[Dict[str, Any]], parent: str, depth: int):
        for acc in accs or []:
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


def _build_flat_views(accounts: List[Dict[str, Any]]) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Returns:
      accounts_flat: [(code, name)]
      accounts_flat_dropdown: [(code, "Name — Path")] (active only)
    """
    flat_all = _flatten_coa_accounts(accounts, include_inactive=True)
    accounts_flat: List[Tuple[str, str]] = [
        (str(a["code"]), str(a["name"])) for a in flat_all if a.get("code") and a.get("name")
    ]
    flat_active = [a for a in flat_all if a.get("active", True)]
    accounts_flat_dropdown: List[Tuple[str, str]] = [
        (str(a["code"]), f'{a["name"]} — {a["path"]}') for a in flat_active
    ]
    return accounts_flat, accounts_flat_dropdown


# ---------- Public API ----------

def load_coa_metadata_and_accounts() -> Dict[str, Any]:
    """
    Returns:
      {
        "accounts": <hierarchical list>,
        "metadata": <dict>,
        "accounts_flat": List[Tuple[code, name]],
        "accounts_flat_dropdown": List[Tuple[code, label]],
      }
    Load order:
      1) JSON file (preferred)
      2) Ledger DB (coa_accounts) fallback
      3) Minimal built-in COA
    """
    # 1) JSON preferred
    loaded = _try_load_from_json()
    if loaded is None:
        # 2) DB fallback
        loaded = _try_load_from_db()
    if loaded is None:
        # 3) Minimal default
        loaded = _minimal_coa()

    accounts, meta = loaded
    accounts_flat, accounts_flat_dropdown = _build_flat_views(accounts)

    return {
        "accounts": accounts,
        "metadata": meta,
        "accounts_flat": accounts_flat,
        "accounts_flat_dropdown": accounts_flat_dropdown,
    }


def list_active_coa_for_dropdown() -> List[Tuple[str, str]]:
    """
    Returns a list suitable for <select> options:
      [(code, "Name — Path"), ...]
    Active accounts only (acc.active != False).
    """
    data = load_coa_metadata_and_accounts()
    return data.get("accounts_flat_dropdown") or data.get("accounts_flat") or []


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
    link = "/coa_mapping?from=ledger"
    if rule_key:
        from urllib.parse import urlencode
        link = f"/coa_mapping?{urlencode({'from': 'ledger', 'rule_key': rule_key})}"

    return {"rule_key": rule_key, "rule": rule, "link": link}


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


def export_coa_markdown(coa_data: Dict[str, Any]) -> str:
    out = []
    # Accept either shape
    accounts = coa_data.get("accounts") if isinstance(coa_data, dict) else None
    meta = coa_data.get("metadata", {}) if isinstance(coa_data, dict) else {}
    if accounts is None and isinstance(coa_data, list):
        accounts = coa_data
        meta = {}
    out.append(f"# Chart of Accounts (COA) — {meta.get('entity_code','')}/{meta.get('jurisdiction_code','')} v{meta.get('coa_version','')}")
    out.append(f"**Currency:** {meta.get('currency_code','')}\n")
    out.append(f"**COA Version:** {meta.get('coa_version','')}")
    out.append(f"**Created:** {meta.get('created_at_utc','')}")
    out.append(f"**Last Updated:** {meta.get('last_updated_utc','')}\n")

    def walk(accs, depth=0):
        for acc in accs or []:
            code = acc.get("code", "")
            name = acc.get("name", "")
            out.append(f"{'  '*depth}- **{code}**: {name}")
            if acc.get("children"):
                walk(acc["children"], depth+1)

    walk(accounts or [])
    return "\n".join(out)


def export_coa_csv(coa_data: Dict[str, Any]) -> str:
    rows = ["code,name,depth"]
    accounts = coa_data.get("accounts") if isinstance(coa_data, dict) else (coa_data if isinstance(coa_data, list) else [])

    def walk(accs, depth=0):
        for acc in accs or []:
            code = acc.get("code", "")
            name = acc.get("name", "")
            rows.append(f"{code},{name},{depth}")
            if acc.get("children"):
                walk(acc["children"], depth+1)

    walk(accounts)
    return "\n".join(rows)


def get_coa_audit_log(limit: int = 50) -> List[Dict[str, Any]]:
    audit_log_path = resolve_coa_audit_log_path()
    try:
        with open(audit_log_path, "r", encoding="utf-8") as alf:
            history = json.load(alf)
    except Exception:
        history = []
    return history[:limit]


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


def validate_coa_json(accounts: Any):
    """
    Accepts either:
      - {"accounts":[...]}
      - [...]
    Validates basic shape.
    """
    raw_accounts = None
    if isinstance(accounts, dict) and "accounts" in accounts:
        raw_accounts = accounts.get("accounts")
    elif isinstance(accounts, list):
        raw_accounts = accounts

    if not isinstance(raw_accounts, list) or not raw_accounts:
        raise ValueError("COA accounts must be a non-empty list.")

    def check(acc):
        if "code" not in acc or "name" not in acc:
            raise ValueError("Each account must have 'code' and 'name'.")
        if "children" in acc and not isinstance(acc["children"], list):
            raise ValueError("'children' must be a list if present.")
        for c in acc.get("children", []):
            check(c)

    for acc in raw_accounts:
        check(acc)
