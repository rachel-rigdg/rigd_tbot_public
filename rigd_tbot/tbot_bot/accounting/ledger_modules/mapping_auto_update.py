# tbot_bot/accounting/ledger_modules/mapping_auto_update.py
"""
Mapping auto-update helper (strict; no feature toggle).

upsert_rule_from_leg(leg, new_account_code, strategy=None, actor=None):
  - Derives a stable rule_key from leg context (broker_code | trn_type | symbol-or-memo [| strategy]).
  - Upserts rule via coa_mapping_table.upsert_rule with a version bump and audit metadata.
  - No DB writes to the ledger here; mapping file only.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tbot_bot.support.decrypt_secrets import load_bot_identity

# Upsert API (versioned write + audit handled in the table module)
from tbot_bot.accounting.coa_mapping_table import upsert_rule

# Optional user resolution (web context). Fallback to "system".
try:  # pragma: no cover
    from tbot_web.support.auth_web import get_current_user
except Exception:  # pragma: no cover
    get_current_user = None  # type: ignore


# --- rule-key derivation (stable, lowercase, pipe-delimited) ---
def _derive_rule_key(leg: Dict[str, Any], strategy: Optional[str]) -> str:
    def norm(x: Any) -> str:
        s = ("" if x is None else str(x)).strip().lower()
        return s.replace("|", "/")

    # broker_code preferred from leg; fallback to identity
    broker = norm(leg.get("broker") or leg.get("broker_code"))
    if not broker:
        try:
            _e, _j, b, _id = load_bot_identity().split("_", 3)
            broker = norm(b)
        except Exception:
            broker = ""

    trn_type = norm(leg.get("trn_type") or leg.get("type") or leg.get("txn_type") or leg.get("action"))
    symbol = norm(leg.get("symbol"))
    memo = norm(leg.get("memo") or leg.get("description") or leg.get("notes") or leg.get("note"))
    sym_or_memo = symbol or memo
    strat = norm(strategy or leg.get("strategy"))

    parts = [p for p in (broker, trn_type, sym_or_memo, strat) if p]
    return "|".join(parts)


def _actor() -> str:
    if callable(get_current_user):
        try:
            u = get_current_user()
            if hasattr(u, "username") and u.username:
                return u.username
            if isinstance(u, str) and u:
                return u
        except Exception:
            pass
    return "system"


def upsert_rule_from_leg(
    leg: Dict[str, Any],
    new_account_code: str,
    strategy: Optional[str] = None,
    actor: Optional[str] = None,
) -> str:
    """
    Strict upsert of a COA mapping rule based on a single leg edit.

    Args:
      leg: dict-like ledger row context (required)
      new_account_code: target COA account code (required; validated by caller)
      strategy: optional strategy context (overrides leg['strategy'] if provided)
      actor: username performing the change; defaults to current web user or 'system'

    Returns:
      version_id returned by coa_mapping_table.upsert_rule(...)
    """
    if not new_account_code or not str(new_account_code).strip():
        raise ValueError("new_account_code is required")

    rule_key = _derive_rule_key(leg or {}, strategy)

    ts_utc = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    context_meta = {
        "source": "inline_edit_strict",
        "ts_utc": ts_utc,
        "broker_code": leg.get("broker") or leg.get("broker_code"),
        "trn_type": leg.get("trn_type") or leg.get("type") or leg.get("txn_type") or leg.get("action"),
        "symbol": leg.get("symbol"),
        "memo": leg.get("memo") or leg.get("description") or leg.get("notes") or leg.get("note"),
        "strategy": strategy or leg.get("strategy"),
        "entry_id": leg.get("id"),
        "group_id": leg.get("group_id"),
        "fitid": leg.get("fitid"),
    }

    actor_val = (actor or "").strip() or _actor()

    # Delegates versioning + audit to the table layer
    version_id = upsert_rule(rule_key=rule_key, account_code=new_account_code, context_meta=context_meta, actor=actor_val)
    return version_id
