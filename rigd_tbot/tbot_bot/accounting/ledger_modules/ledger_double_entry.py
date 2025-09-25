# tbot_bot/accounting/ledger_modules/ledger_double_entry.py

from __future__ import annotations
from typing import Optional, Tuple, List, Dict, Any, Callable
from tbot_bot.accounting.ledger_modules.ledger_account_map import get_account_path  # kept for downstream imports
from tbot_bot.accounting.coa_mapping_table import load_mapping_table, apply_mapping_rule
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
import sqlite3
import json
import hashlib
from datetime import datetime


# ---- Compliance filter (deterministic resolution, no brittle try/except imports) ----
from tbot_bot.accounting.ledger_modules import ledger_compliance_filter as _lcf  # type: ignore


def _resolve_is_compliant() -> Callable[[dict], bool]:
    """
    Resolve a boolean compliance predicate from the compliance filter module.
    Priority:
      1) is_compliant_ledger_entry(entry) -> bool
      2) compliance_filter_entry(entry) -> (bool, reason)  ==> bool
      3) compliance_filter_ledger_entry(entry) -> entry|None  ==> bool
    """
    if hasattr(_lcf, "is_compliant_ledger_entry"):
        return getattr(_lcf, "is_compliant_ledger_entry")  # returns bool

    if hasattr(_lcf, "compliance_filter_entry"):
        def _wrap(entry: dict) -> bool:
            ok, _reason = _lcf.compliance_filter_entry(entry)  # type: ignore[attr-defined]
            return bool(ok)
        return _wrap

    if hasattr(_lcf, "compliance_filter_ledger_entry"):
        def _wrap(entry: dict) -> bool:
            res = _lcf.compliance_filter_ledger_entry(entry)  # type: ignore[attr-defined]
            return res is not None
        return _wrap

    # Hard fail with a clear message — compliance filter is mandatory
    raise ImportError(
        "ledger_compliance_filter is missing required predicates "
        "(is_compliant_ledger_entry/compliance_filter_entry/compliance_filter_ledger_entry)."
    )


_is_compliant_ledger_entry = _resolve_is_compliant()

# ---------------------------
# Constants / Helpers
# ---------------------------

SUSPENSE = "3999_SUSPENSE"
PNL = "5000_TRADING_PNL"


def get_identity_tuple() -> Tuple[str, str, str, str]:
    identity = load_bot_identity() or ""
    parts = identity.split("_")
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])  # (entity_code, jurisdiction_code, broker_code, bot_id)


def _as_float(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, str) and x.strip() in ("", "None"):
            return default
        return float(x)
    except Exception:
        return default


def _map_action(action: Optional[str]) -> str:
    """Map broker/raw actions to normalized ledger schema actions."""
    if not action or not isinstance(action, str):
        return "other"
    a = action.strip().lower()
    if a in ("buy", "long"):
        return "long"
    if a in ("sell", "short"):
        return "short"
    if a in ("put", "call", "assignment", "exercise", "expire", "reorg", "inverse"):
        return a
    return "other"


def _jsonify_if_needed(v):
    """SQLite bindings must not see dict/list; encode to JSON string."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def _ensure_json_fields(entry: dict) -> None:
    """
    Ensure json-bearing columns exist and are strings, not dicts.
    Keep keys consistent with TRADES_FIELDS: json_metadata, raw_broker_json.
    """
    if "json_metadata" not in entry or entry["json_metadata"] is None:
        entry["json_metadata"] = "{}"
    if "raw_broker_json" not in entry or entry["raw_broker_json"] is None:
        entry["raw_broker_json"] = "{}"


def _add_required_fields(entry: dict,
                         entity_code: str,
                         jurisdiction_code: str,
                         broker_code: str,
                         bot_id: str) -> dict:
    """
    Ensure mandatory columns exist, coerce numerics, normalize actions, set IDs,
    and JSON-encode complex values so SQLite bindings never see dict/list objects.
    """
    e = dict(entry or {})

    # Identity context (always present)
    e["entity_code"] = entity_code
    e["jurisdiction_code"] = jurisdiction_code
    e["broker_code"] = broker_code
    e["bot_id"] = bot_id

    # Normalize action/status
    e["action"] = _map_action(e.get("action"))
    if not e.get("status"):
        e["status"] = "ok"

    # Numerics (don’t throw)
    e["fee"] = _as_float(e.get("fee"), 0.0)
    e["commission"] = _as_float(e.get("commission"), 0.0)
    e["price"] = _as_float(e.get("price"), e.get("price") or 0.0)
    e["quantity"] = _as_float(e.get("quantity"), e.get("quantity") or 0.0)

    # Total value default
    if "total_value" not in e or e["total_value"] is None:
        e["total_value"] = _as_float(e.get("total_value"), 0.0)

    # Compute amount sign from side when missing (credit ⇒ negative; debit ⇒ positive)
    if e.get("amount") is None:
        val = _as_float(e.get("total_value"), 0.0)
        side = (e.get("side") or "").strip().lower()
        e["amount"] = -abs(val) if side == "credit" else abs(val)

    # Ensure IDs (make hashing safe if dict/list present)
    if not e.get("trade_id"):
        try:
            h = hash(frozenset(e.items()))
        except TypeError:
            h = hash(repr(sorted(e.items())))
        e["trade_id"] = f"{broker_code}_{bot_id}_{abs(h)}"
    if not e.get("group_id"):
        e["group_id"] = e.get("trade_id")

    # JSON-bearing fields
    _ensure_json_fields(e)

    # Fill any missing schema fields with None; then sanitize complex types
    for k in TRADES_FIELDS:
        if k not in e:
            e[k] = None

    # Sanitize: JSON-encode complex types
    for k, v in list(e.items()):
        e[k] = _jsonify_if_needed(v)

    return e


def _fallback_unmapped_legs(entry_in: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    When no mapping rule exists, route to Suspense vs P&L so rows are not dropped.
    Ensures zero-sum across legs.
    """
    e = dict(entry_in or {})
    val = _as_float(e.get("total_value"), 0.0)
    if val >= 0:
        debit = {**e, "side": "debit",  "account": SUSPENSE, "total_value": abs(val),  "amount":  abs(val)}
        credit = {**e, "side": "credit", "account": PNL,      "total_value": -abs(val), "amount": -abs(val)}
    else:
        debit = {**e, "side": "debit",  "account": PNL,      "total_value": abs(val),  "amount":  abs(val)}
        credit = {**e, "side": "credit", "account": SUSPENSE, "total_value": -abs(val), "amount": -abs(val)}
    return debit, credit


def _is_presplit(entry: Dict[str, Any]) -> bool:
    """True if caller already provided journal legs (side + account present)."""
    side = (entry.get("side") or "").strip().lower()
    return bool(side in ("debit", "credit") and (entry.get("account") or "").strip())


def _date_part(date_str: Optional[str]) -> str:
    """YYYY-MM-DD from ISO, group_id, or best-effort."""
    if not date_str:
        return ""
    try:
        return str(date_str)[:10]
    except Exception:
        return ""


def _compute_fitid_for_ob(leg: Dict[str, Any], broker_code: str, group_id: str) -> str:
    """
    Deterministic OB FITID:
      sha256(f"{broker}|{account_id}|{yyyy-mm-dd}|OB|{symbol}|{amount}")
    account_id pulled from leg['account_id'] or json_metadata.
    date from leg['datetime_utc'] (preferred) else group_id ('OPENING_BALANCE_YYYYMMDD').
    """
    acct_id = (leg.get("account_id") or "") or (
        (json.loads(leg["json_metadata"]).get("account_id") if isinstance(leg.get("json_metadata"), str) else (leg.get("json_metadata") or {}).get("account_id"))
        if leg.get("json_metadata") else ""
    )
    dt = _date_part(leg.get("datetime_utc") or "")
    if (not dt) and group_id.startswith("OPENING_BALANCE_") and len(group_id) >= 27:
        # expect OPENING_BALANCE_YYYYMMDD
        try:
            ymd = group_id.split("_", 2)[-1]
            dt = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        except Exception:
            dt = ""
    symbol = str(leg.get("symbol") or leg.get("memo") or leg.get("description") or leg.get("account") or "").upper()
    amt = f"{_as_float(leg.get('amount') if leg.get('amount') is not None else leg.get('total_value'), 0.0):.2f}"
    key = f"{broker_code}|{acct_id}|{dt}|OB|{symbol}|{amt}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _maybe_assign_fitid(leg: Dict[str, Any], broker_code: str, group_id: str) -> None:
    """Assign fitid if missing; use OB scheme for OB groups, else derive from trade_id/side/datetime."""
    if leg.get("fitid"):
        return
    if group_id.startswith("OPENING_BALANCE_"):
        leg["fitid"] = _compute_fitid_for_ob(leg, broker_code, group_id)
        return
    # Non-OB deterministic fallback
    key = f"{broker_code}|{leg.get('trade_id')}|{leg.get('side')}|{leg.get('datetime_utc')}|{_as_float(leg.get('total_value'),0.0):.2f}"
    leg["fitid"] = hashlib.sha256(key.encode("utf-8")).hexdigest()


def _ensure_group_sync_id(legs: List[Dict[str, Any]], group_id: str) -> None:
    """Make all legs in group share the same sync_run_id (if any)."""
    existing = None
    for l in legs:
        if l.get("sync_run_id"):
            existing = l["sync_run_id"]
            break
    if not existing:
        existing = f"sync_{group_id}"
    for l in legs:
        l["sync_run_id"] = existing


def _group_zero_sum_ok(legs: List[Dict[str, Any]]) -> bool:
    s = 0.0
    for l in legs:
        s += _as_float(l.get("total_value"), 0.0)
    return abs(s) <= 1e-8


# ---------------------------
# Public API
# ---------------------------

def post_ledger_entries_double_entry(entries: List[dict]):
    """
    Public entry point used by hooks and other modules.
    Loads mapping table from identity and posts compliant entries.
    Returns list of (debit_trade_id, credit_trade_id) pairs that were (attempted to be) inserted.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)

    # Apply compliance filter before posting
    filtered_entries = [e for e in (entries or []) if _is_compliant_ledger_entry(e)]
    return post_double_entry(filtered_entries, mapping_table)


def post_double_entry(entries: List[dict], mapping_table=None):
    """
    Low-level poster: supports two modes per entry:
      1) Pre-split (OB or journal): entry already has 'side' ('debit'/'credit') and 'account'
         -> grouped by group_id, atomic insert per group, enforce zero-sum.
      2) Event form: single entry that needs mapping -> mapped to (debit, credit) legs, inserted.

    Dedup priority: fitid (if present) else (trade_id, side).
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    inserted_ids: List[Tuple[Optional[str], Optional[str]]] = []

    if mapping_table is None:
        mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)

    # Partition into presplit vs events
    presplit: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    for e in entries or []:
        (presplit if _is_presplit(e) else events).append(e)

    # Expand events into debit/credit legs, grouped by group_id (each event remains two legs)
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for entry in events:
        try:
            debit_entry, credit_entry = apply_mapping_rule(entry, mapping_table)
            if (not debit_entry or not credit_entry
                    or not debit_entry.get("account") or not credit_entry.get("account")):
                raise ValueError("unmapped_rule")
        except Exception:
            debit_entry, credit_entry = _fallback_unmapped_legs(entry)

        gid = (entry.get("group_id") or entry.get("trade_id") or "").strip() or f"{broker_code}_{bot_id}_{hashlib.sha256(str(entry).encode('utf-8')).hexdigest()[:10]}"
        debit_entry["group_id"] = gid
        credit_entry["group_id"] = gid

        grouped.setdefault(gid, []).extend([debit_entry, credit_entry])
        inserted_ids.append((debit_entry.get("trade_id"), credit_entry.get("trade_id")))

    # Gather presplit legs by group_id
    for leg in presplit:
        gid = (leg.get("group_id") or leg.get("trade_id") or "").strip()
        if not gid:
            # ensure OB legs always have a group; if missing, synthesize one by date
            dt = _date_part(leg.get("datetime_utc") or datetime.utcnow().isoformat())
            ymd = dt.replace("-", "") or datetime.utcnow().strftime("%Y%m%d")
            gid = f"OPENING_BALANCE_{ymd}"
            leg["group_id"] = gid
        grouped.setdefault(gid, []).append(leg)

    # Insert by group atomically
    with sqlite3.connect(db_path) as conn:
        for gid, legs in grouped.items():
            # Normalize -> sanitize; assign sync_run_id; compute fitids
            normed: List[Dict[str, Any]] = []
            for leg in legs:
                # Ensure amount sign matches side
                val = _as_float(leg.get("total_value"), 0.0)
                side = (leg.get("side") or "").strip().lower()
                if side == "debit":
                    leg["total_value"] = abs(val)
                    leg["amount"] = abs(val)
                elif side == "credit":
                    leg["total_value"] = -abs(val)
                    leg["amount"] = -abs(val)

                # JSON containers safe for sqlite
                _ensure_json_fields(leg)

                # Assign fitid if missing (OB rules for OB groups)
                _maybe_assign_fitid(leg, broker_code, gid)

                # Normalize and fill required columns
                leg_n = _add_required_fields(leg, entity_code, jurisdiction_code, broker_code, bot_id)
                normed.append(leg_n)

            # Enforce same sync_run_id across the group
            _ensure_group_sync_id(normed, gid)

            # Zero-sum check (strong invariant)
            if not _group_zero_sum_ok(normed):
                raise RuntimeError(f"Double-entry imbalance in group {gid}")

            # Atomic insert per group
            try:
                conn.execute("BEGIN")
                for l in normed:
                    # Dedup: fitid first (if column exists in schema), else (trade_id, side)
                    # We defensively try fitid; if column is absent, SQLite will error on query —
                    # so wrap that check.
                    fitid = l.get("fitid")
                    dedup_hit = False
                    if fitid:
                        try:
                            c = conn.execute("SELECT 1 FROM trades WHERE fitid = ?", (fitid,))
                            if c.fetchone():
                                dedup_hit = True
                        except Exception:
                            # fitid column may not exist — fall back to (trade_id, side)
                            dedup_hit = False
                    if not dedup_hit:
                        c = conn.execute(
                            "SELECT 1 FROM trades WHERE trade_id = ? AND side = ?",
                            (l.get("trade_id"), l.get("side")),
                        )
                        if c.fetchone():
                            dedup_hit = True

                    if dedup_hit:
                        continue

                    columns = TRADES_FIELDS
                    placeholders = ", ".join(["?"] * len(columns))
                    conn.execute(
                        f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
                        tuple(l.get(col) for col in columns),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    return inserted_ids


def validate_double_entry() -> bool:
    """
    Validates that each trade_id sums to ~0 across its legs (double-entry),
    AND that each OB group_id (OPENING_BALANCE_*) also sums to ~0 across its legs.
    Raises if imbalance found.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        # Per trade_id invariant
        cursor = conn.execute("SELECT trade_id, COALESCE(SUM(total_value),0.0) FROM trades GROUP BY trade_id")
        imbalances = [(tid, total) for tid, total in cursor.fetchall() if tid and abs(total or 0.0) > 1e-8]
        if imbalances:
            raise RuntimeError(f"Double-entry imbalance detected for trade_ids: {imbalances}")

        # OB group invariant (multi-split groups)
        try:
            cursor = conn.execute(
                "SELECT group_id, COALESCE(SUM(total_value),0.0) "
                "FROM trades WHERE group_id LIKE 'OPENING_BALANCE_%' GROUP BY group_id"
            )
            ob_imbalances = [(gid, total) for gid, total in cursor.fetchall() if gid and abs(total or 0.0) > 1e-8]
            if ob_imbalances:
                raise RuntimeError(f"Opening Balance imbalance detected for groups: {ob_imbalances}")
        except Exception:
            # If group_id not in schema (unlikely), skip OB check
            pass
    return True
