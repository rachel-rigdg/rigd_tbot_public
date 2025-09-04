# tbot_bot/accounting/coa_mapping_table.py
# COA mapping table for broker ledger sync: persistent, versioned, and auto-extending.
# Stores mapping rules for broker transaction types to bot COA accounts.
# All edits are append-only; each mapping change creates a new snapshot/version for audit/rollback.
# Seed policy: do NOT include BUY/SELL/SHORT_OPEN/SHORT_COVER mappings; the posting router computes realized P&L.

import os
import json
from datetime import datetime, timezone
from pathlib import Path
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

def _seed_path() -> Path:
    # Default seed JSON (created earlier in defaults/)
    return Path(__file__).resolve().parents[0] / "defaults" / "coa_mapping_seed.json"

# ----------------------------------------------------------------------
# Seed defaults (Dividend/Interest/Deposit/Withdrawal/Fee/Commission; NO trade legs)
# ----------------------------------------------------------------------
_ALLOWED_SEED_TYPES = {
    "DIV", "DIVIDEND",
    "INT", "INTEREST",
    "DEPOSIT", "TRANSFER_IN",
    "WITHDRAWAL", "TRANSFER_OUT",
    "FEE", "COMMISSION",
}

def _default_seed_rows() -> List[Dict[str, Any]]:
    """
    In-code fallback if the external seed file is missing or empty.
    Only non-trade cash/income/equity admin events are seeded.
    """
    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    return [
        # DIVIDEND/INTEREST -> Dr Cash, Cr Income
        {"broker": None, "type": "DIVIDEND", "subtype": None, "description": None,
         "debit_account": "Assets:Brokerage:Cash", "credit_account": "Income:Dividends Earned",
         "updated_by": "seed", "updated_at": now_iso},
        {"broker": None, "type": "DIV", "subtype": None, "description": None,
         "debit_account": "Assets:Brokerage:Cash", "credit_account": "Income:Dividends Earned",
         "updated_by": "seed", "updated_at": now_iso},
        {"broker": None, "type": "INTEREST", "subtype": None, "description": None,
         "debit_account": "Assets:Brokerage:Cash", "credit_account": "Income:Interest Income",
         "updated_by": "seed", "updated_at": now_iso},
        {"broker": None, "type": "INT", "subtype": None, "description": None,
         "debit_account": "Assets:Brokerage:Cash", "credit_account": "Income:Interest Income",
         "updated_by": "seed", "updated_at": now_iso},
        # DEPOSIT / TRANSFER_IN -> Dr Cash, Cr Equity:Owner Contributions
        {"broker": None, "type": "DEPOSIT", "subtype": None, "description": None,
         "debit_account": "Assets:Brokerage:Cash", "credit_account": "Equity:Capital Contributions",
         "updated_by": "seed", "updated_at": now_iso},
        {"broker": None, "type": "TRANSFER_IN", "subtype": None, "description": None,
         "debit_account": "Assets:Brokerage:Cash", "credit_account": "Equity:Capital Contributions",
         "updated_by": "seed", "updated_at": now_iso},
        # WITHDRAWAL / TRANSFER_OUT -> Dr Equity:Owner Withdrawals, Cr Cash
        {"broker": None, "type": "WITHDRAWAL", "subtype": None, "description": None,
         "debit_account": "Equity:Owner Withdrawals", "credit_account": "Assets:Brokerage:Cash",
         "updated_by": "seed", "updated_at": now_iso},
        {"broker": None, "type": "TRANSFER_OUT", "subtype": None, "description": None,
         "debit_account": "Equity:Owner Withdrawals", "credit_account": "Assets:Brokerage:Cash",
         "updated_by": "seed", "updated_at": now_iso},
        # FEE / COMMISSION -> Dr Expenses:Brokerage Fees, Cr Cash
        {"broker": None, "type": "FEE", "subtype": None, "description": None,
         "debit_account": "Expenses:Brokerage Fees", "credit_account": "Assets:Brokerage:Cash",
         "updated_by": "seed", "updated_at": now_iso},
        {"broker": None, "type": "COMMISSION", "subtype": None, "description": None,
         "debit_account": "Expenses:Brokerage Fees", "credit_account": "Assets:Brokerage:Cash",
         "updated_by": "seed", "updated_at": now_iso},
    ]

def _load_default_seed() -> List[Dict[str, Any]]:
    """
    Load a small, stable starter set of mapping rules from defaults/coa_mapping_seed.json.
    Falls back to in-code defaults if the JSON file is missing.
    Filters out trade-close/open actions (BUY/SELL/SHORT_OPEN/SHORT_COVER).
    Coerces single-sided 'coa_account' seeds into two-sided debit/credit by type.
    """
    p = _seed_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            rows_in = data.get("mappings") or data.get("rows") or data.get("rules") or []
            out: List[Dict[str, Any]] = []
            now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

            for r in rows_in:
                if not isinstance(r, dict):
                    continue
                t_raw = r.get("type")
                t_norm = _normalize_type(t_raw)
                if t_norm not in _ALLOWED_SEED_TYPES:
                    # skip BUY/SELL/SHORT_* and anything else not whitelisted
                    continue

                # Prefer explicit debit/credit if provided
                debit = r.get("debit_account") or r.get("debit")
                credit = r.get("credit_account") or r.get("credit")
                single = r.get("coa_account")

                # If only single target is provided, coerce to two-sided by type semantics
                if (not debit or not credit) and single:
                    if t_norm in {"FEE", "COMMISSION", "WITHDRAWAL", "TRANSFER_OUT"}:
                        debit = debit or single
                        credit = credit or "Assets:Brokerage:Cash"
                    elif t_norm in {"DIV", "DIVIDEND", "INT", "INTEREST"}:
                        debit = debit or "Assets:Brokerage:Cash"
                        credit = credit or single
                    elif t_norm in {"DEPOSIT", "TRANSFER_IN"}:
                        debit = debit or "Assets:Brokerage:Cash"
                        credit = credit or single

                out.append({
                    "broker": r.get("broker"),
                    "type": t_norm,
                    "subtype": r.get("subtype"),
                    "description": r.get("description"),
                    "debit_account": debit,
                    "credit_account": credit,
                    "updated_by": "seed",
                    "updated_at": now_iso,
                })

            # If file present but yielded nothing after filtering, fall back
            return [row for row in out if row.get("debit_account") or row.get("credit_account")] or _default_seed_rows()
    except Exception:
        pass
    return _default_seed_rows()

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
    table.setdefault("mappings", [])
    table.setdefault("rules", [])      # programmatic single-account rules (optional)
    table.setdefault("history", [])
    table.setdefault("version", 1)

def _maybe_seed_defaults(table: Dict[str, Any]) -> bool:
    """
    If both 'mappings' and 'rules' are empty, seed with default starter rules.
    Returns True if seeding occurred.
    """
    if (not table.get("mappings")) and (not table.get("rules")):
        table["mappings"] = _load_default_seed()
        table["change_reason"] = "seed_default"
        table["last_updated_by"] = "system"
        return True
    return False

def load_mapping_table(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None) -> Dict[str, Any]:
    """
    Loads the current mapping table (JSON). If missing or empty, seeds with defaults.
    """
    path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    if not path.exists():
        table = {"mappings": [], "rules": [], "version": 1, "history": [], "coa_version": "v1.0.0"}
        _ensure_core_metadata(table)
        _maybe_seed_defaults(table)
        # Persist initial file (seeded or not)
        save_mapping_table(table, entity_code, jurisdiction_code, broker_code, bot_id, reason="init")
        return table

    with open(path, "r", encoding="utf-8") as f:
        table = json.load(f)
    _ensure_core_metadata(table)

    # If an existing file is empty of rules, seed and persist once
    if _maybe_seed_defaults(table):
        save_mapping_table(table, entity_code, jurisdiction_code, broker_code, bot_id, reason="seed_default")

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
    # Coerce reason/actor to non-empty (prevent None propagation to history)
    reason = (reason or "update")
    actor = (actor or "system")

    _ensure_core_metadata(table)
    path = _get_mapping_path(entity_code, jurisdiction_code, broker_code, bot_id)
    os.makedirs(path.parent, exist_ok=True)

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_iso = now.isoformat()
    table["version"] = int(table.get("version", 1)) + 1
    table["last_updated_by"] = actor
    table["change_reason"] = reason

    # Append structured history snapshot
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
        pass
    return codes

def _derive_rule_key_from_context(context_meta: Dict[str, Any]) -> str:
    """
    Stable, lowercase, pipe-delimited key:

        broker_like | type_like | symbol-or-memo | strategy?
    """
    def norm(x):
        s = ("" if x is None else str(x)).strip().lower()
        return s.replace("|", "/")

    broker_like = (
        context_meta.get("broker")
        or context_meta.get("broker_code")
        or context_meta.get("import_source")
    )
    type_like = (
        context_meta.get("trn_type")
        or context_meta.get("type")
        or context_meta.get("txn_type")
        or context_meta.get("action")
        or context_meta.get("subtype")
        or context_meta.get("import_type")
    )
    symbol = context_meta.get("symbol")
    memo = (
        context_meta.get("memo")
        or context_meta.get("description")
        or context_meta.get("note")
        or context_meta.get("notes")
    )
    strat = context_meta.get("strategy")

    parts = [norm(x) for x in (broker_like, type_like, (symbol or memo), strat) if x]
    return "|".join(parts)

# ----------------------------------------------------------------------
# Type normalization for matching legacy/normalized actions
# ----------------------------------------------------------------------
def _normalize_type(v: Optional[str]) -> str:
    if not v:
        return ""
    a = str(v).strip().lower()

    # Long/open/close (cash equities)
    if a in ("buy", "long", "filled_buy", "buy_to_open", "bto"):
        return "BUY"
    if a in ("sell", "filled_sell", "sell_to_close", "stc"):
        return "SELL"

    # Short mechanics (explicit)
    if a in ("sell_short", "short_open", "sell_to_open", "sto"):
        return "SHORT_OPEN"
    if a in ("buy_to_cover", "cover", "btc"):
        return "SHORT_COVER"

    # Income & admin cash movements
    if a in ("dividend", "div", "cash_dividend", "div_cash"):
        return "DIVIDEND"
    if a in ("interest", "int", "cash_interest"):
        return "INTEREST"
    if a in ("deposit", "transfer_in", "journal_in", "external_cash_in", "cash_in"):
        return "DEPOSIT"
    if a in ("withdrawal", "transfer_out", "journal_out", "external_cash_out", "cash_out"):
        return "WITHDRAWAL"
    if a in ("fee", "commission", "reg_fee", "broker_fee"):
        return "FEE"

    # Fallback uppercased
    return a.upper()

def _subst_symbol_placeholder(acct: Optional[str], symbol: Optional[str]) -> str:
    s = (acct or "").strip()
    if "{SYMBOL}" in s:
        s = s.replace("{SYMBOL}", (symbol or "UNKNOWN").upper())
    return s

# ----------------------------------------------------------------------
# Programmatic API (canonical)
# ----------------------------------------------------------------------
def upsert_rule(rule_key: str, account_code: str, context_meta: Optional[Dict[str, Any]], actor: str) -> str:
    """
    Create or update a programmatic mapping rule (single target account_code).
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
            cm = dict(r.get("context_meta") or {})
            cm.update({k: v for k, v in (context_meta or {}).items() if v not in (None, "")})
            r["context_meta"] = cm
            r["updated_by"] = actor
            r["updated_at_utc"] = now_iso
            updated = True
            break
    if not updated:
        rules.append({
            "rule_key": rule_key,
            "account_code": account_code,
            "context_meta": context_meta or {},
            "created_by": actor,
            "created_at_utc": now_iso,
            "updated_by": actor,
            "updated_at_utc": now_iso,
        })
    table["rules"] = rules
    table["last_updated_by"] = actor
    table["change_reason"] = (context_meta.get("source") if isinstance(context_meta, dict) else None) or "upsert_rule"

    return save_mapping_table(table, reason=table["change_reason"], actor=table["last_updated_by"])

def upsert_rule_from_leg(leg: Dict[str, Any], account_code: str, actor: str) -> str:
    if not isinstance(leg, dict):
        raise ValueError("leg must be a dict")
    if not account_code or not isinstance(account_code, str):
        raise ValueError("account_code is required")

    memo = leg.get("description") or leg.get("notes") or leg.get("memo") or None
    jm = leg.get("json_metadata")
    if memo is None and isinstance(jm, (str, bytes)):
        try:
            jm_obj = json.loads(jm)
            if isinstance(jm_obj, dict):
                memo = jm_obj.get("memo") or jm_obj.get("description") or jm_obj.get("raw_memo")
        except Exception:
            pass
    elif memo is None and isinstance(jm, dict):
        memo = jm.get("memo") or jm.get("description") or jm.get("raw_memo")

    context_meta: Dict[str, Any] = {
        "broker": leg.get("broker"),
        "broker_code": leg.get("broker_code"),
        "import_source": leg.get("import_source"),
        "type": leg.get("action") or leg.get("type") or leg.get("txn_type") or leg.get("subtype"),
        "import_type": leg.get("import_type"),
        "symbol": leg.get("symbol"),
        "memo": memo,
        "strategy": leg.get("strategy"),
        "source": "upsert_rule_from_leg",
        "trade_id": leg.get("trade_id"),
        "group_id": leg.get("group_id"),
    }
    return upsert_rule(rule_key="", account_code=account_code, context_meta=context_meta, actor=actor)

# ----------------------------------------------------------------------
# Legacy APIs (retained)
# ----------------------------------------------------------------------
def save_mapping_table_legacy_snapshot_only(table, entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None):
    return save_mapping_table(table, entity_code, jurisdiction_code, broker_code, bot_id)

def assign_mapping(mapping_rule, user, reason=None) -> str:
    """
    Legacy field-based mapping upsert.
    Returns the version_id string from the persisted snapshot.
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
    table["change_reason"] = (reason or "manual assignment")
    return save_mapping_table(table, reason=table["change_reason"], actor=user)

def get_mapping_for_transaction(txn, mapping_table=None):
    """
    Look up the COA mapping for a transaction dict.
    Supports both legacy field-based mappings and programmatic rules.
    """
    if mapping_table is None:
        mapping_table = load_mapping_table()

    # Normalize the txn "type"/action for matching
    txn_type_raw = txn.get("type") or txn.get("txn_type") or txn.get("action")
    txn_type = _normalize_type(txn_type_raw)
    txn_broker = (txn.get("broker") or txn.get("broker_code") or "").strip() or None

    # 1) Legacy field-based mappings (with normalized type compare)
    for rule in mapping_table.get("mappings", []):
        rule_type = _normalize_type(rule.get("type"))
        # Broker match: if rule specifies broker, it must match; else wildcard
        broker_ok = (rule.get("broker") is None) or (rule.get("broker") == txn_broker)
        subtype_ok = (rule.get("subtype") is None) or (rule.get("subtype") == txn.get("subtype"))
        desc_ok = (rule.get("description") is None) or (rule.get("description") == txn.get("description"))
        if broker_ok and subtype_ok and desc_ok and rule_type == txn_type:
            return rule

    # 2) Programmatic single-account rules (optional): derive key and return a simplified view
    key = _derive_rule_key_from_context(txn or {})
    for r in mapping_table.get("rules", []):
        if r.get("rule_key") == key:
            return {"broker": txn_broker, "type": txn_type, "coa_account": r.get("account_code"), "rule_key": key}
    return None

def flag_unmapped_transaction(txn, user="system") -> str:
    table = load_mapping_table()
    table.setdefault("unmapped", []).append({
        "transaction": txn,
        "flagged_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "flagged_by": user
    })
    return save_mapping_table(table, reason="flag_unmapped", actor=user)

def rollback_mapping_version(version):
    versions_dir = _get_versions_dir()
    if not versions_dir.exists():
        return False
    for fname in sorted(os.listdir(versions_dir), reverse=True):
        if fname.startswith(f"coa_mapping_table_v{version}_"):
            path = versions_dir / fname
            with open(path, "r", encoding="utf-8") as fsrc:
                snapshot = json.load(fsrc)
            save_mapping_table(snapshot, reason="rollback", actor="system")
            return True
    return False

def export_mapping_table():
    table = load_mapping_table()
    _ensure_core_metadata(table)
    return json.dumps(table, indent=2)

def import_mapping_table(json_data, user="import") -> str:
    table = json.loads(json_data)
    _ensure_core_metadata(table)
    # If an import wipes all rules, re-seed defaults once to avoid a dead-start mapping table
    seeded = False
    if not table.get("mappings") and not table.get("rules"):
        table["mappings"] = _load_default_seed()
        table["change_reason"] = "imported+seed_default"
        seeded = True
    table["last_updated_by"] = user
    table["change_reason"] = table.get("change_reason") or ("imported" if not seeded else "imported+seed_default")
    return save_mapping_table(table, reason=table["change_reason"], actor=user)

def apply_mapping_rule(entry, mapping_table=None):
    """
    Build (debit, credit) legs using the mapping table.
    - Supports legacy 'mappings' rules (with {SYMBOL} placeholder).
    - If no rule found, caller may fallback to Suspense/PNL.
    """
    if mapping_table is None:
        mapping_table = load_mapping_table()

    mapping = get_mapping_for_transaction(entry, mapping_table)

    # Legacy two-sided mapping
    if mapping and ("debit_account" in mapping or "credit_account" in mapping):
        symbol = entry.get("symbol")
        debit_acct = _subst_symbol_placeholder(mapping.get("debit_account"), symbol)
        credit_acct = _subst_symbol_placeholder(mapping.get("credit_account"), symbol)

        debit_entry = dict(entry)
        credit_entry = dict(entry)
        amt = abs(float(debit_entry.get("total_value", 0) or 0.0))
        debit_entry["total_value"] = +amt
        credit_entry["total_value"] = -amt
        debit_entry["side"] = "debit"
        credit_entry["side"] = "credit"
        debit_entry["account"] = debit_acct or "Uncategorized:Debit"
        credit_entry["account"] = credit_acct or "Uncategorized:Credit"
        return debit_entry, credit_entry

    # Programmatic single-account rules are not sufficient to produce both legs here;
    # let caller fall back to Suspense/PNL if no legacy mapping matched.
    return None, None
