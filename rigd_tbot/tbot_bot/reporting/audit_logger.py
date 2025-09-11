# tbot_bot/reporting/audit_logger.py
# Structured audit logging for all allocation, reserve, trade, and holdings management actions.
# Called from all trade logic, float/rebalance/tax/payroll, and UI override actions.

import os
import json
from typing import Optional, Dict, Any
from datetime import datetime

from tbot_bot.support import path_resolver


def _get_audit_log_path(bot_identity: Optional[str] = None) -> str:
    """
    Always resolves to output/{BOT_IDENTITY}/logs/holdings_audit.log
    Falls back to shared output/logs during bootstrap or when identity is unavailable.
    """
    try:
        return path_resolver.resolve_holdings_audit_log_path(bot_identity)
    except Exception:
        return path_resolver.resolve_output_path("logs/holdings_audit.log")


def _require_non_empty_str(name: str, value: Optional[str]) -> str:
    """
    Enforce a non-null, non-empty string. No defaults allowed.
    """
    if value is None:
        raise ValueError(f"{name} is required and must be a non-empty string")
    s = str(value).strip()
    if not s:
        raise ValueError(f"{name} is required and must be a non-empty string")
    return s


def _normalize_actor(actor: Optional[str], user: Optional[str]) -> str:
    """
    Prefer explicit 'actor', but accept legacy 'user' kwarg.
    Falls back to 'system' if neither is provided or both are empty.
    """
    for cand in (actor, user):
        if cand is not None:
            s = str(cand).strip()
            if s:
                return s
    return "system"


def audit_log_event(
    event_type: str,
    actor: Optional[str] = None,  # was required; kept positional for compat, now optional
    /,
    *,
    user: Optional[str] = None,   # NEW: legacy alias accepted (e.g., user="holdings_manager")
    reference: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    bot_identity: Optional[str] = None,
    **_ignored,                   # tolerate unexpected kwargs from older call sites
) -> None:
    """
    Appends a single audit event to holdings_audit.log with UTC ISO-8601 timestamp.

    REQUIRED:
      - event_type: Non-null, non-empty string.

    ACTOR:
      - actor: preferred
      - user:  accepted as a legacy alias (mapped to actor)
      If neither provided/non-empty, defaults to "system" (prevents crashes).

    OPTIONAL:
      - reference:  ID or context string.
      - details:    JSON-serializable dict for full event context.
      - reason:     Human-readable rationale for the action.
      - bot_identity: Explicit identity string override.
    """
    etype = _require_non_empty_str("event_type", event_type)
    who = _normalize_actor(actor, user)

    log_file = _get_audit_log_path(bot_identity)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    record: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "event_type": etype,
        "actor": who,
        "reference": reference,
        "reason": reason,
        "details": details if details is not None else {},
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_holdings_event(
    event_type: str,
    actor: Optional[str] = None,
    message: str = "",
    /,
    *,
    user: Optional[str] = None,   # accept legacy alias here as well
    reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    bot_identity: Optional[str] = None,
) -> None:
    """
    Legacy convenience wrapper that logs a simpler event line with message text.
    Accepts 'actor' or legacy 'user'; defaults to 'system' if neither provided.
    """
    etype = _require_non_empty_str("event_type", event_type)
    who = _normalize_actor(actor, user)

    log_file = _get_audit_log_path(bot_identity)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    record: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "event_type": etype,
        "actor": who,
        "message": message,
        "reason": reason,
    }

    if isinstance(extra, dict) and extra:
        # Merge without overwriting core keys
        for k, v in extra.items():
            if k not in record:
                record[k] = v

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
