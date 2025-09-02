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


def audit_log_event(
    event_type: str,
    actor: str,
    /,
    *,
    reference: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    bot_identity: Optional[str] = None,
) -> None:
    """
    Appends a single audit event to holdings_audit.log with UTC ISO-8601 timestamp.

    REQUIRED (no defaults):
      - event_type: Non-null, non-empty string.
      - actor:      Non-null, non-empty string.

    OPTIONAL (pass through as-is, no substitution defaults):
      - reference:  ID or context string.
      - details:    JSON-serializable dict for full event context.
      - reason:     Human-readable rationale for the action.
      - bot_identity: Explicit identity string override.

    Raises:
      ValueError if event_type or actor are missing/empty.
    """
    etype = _require_non_empty_str("event_type", event_type)
    who = _require_non_empty_str("actor", actor)

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
    actor: str,
    message: str,
    /,
    *,
    reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    bot_identity: Optional[str] = None,
) -> None:
    """
    Legacy convenience wrapper that logs a simpler event line with message text.
    Still enforces non-null event_type and actor; no defaults.

    Raises:
      ValueError if event_type or actor are missing/empty.
    """
    etype = _require_non_empty_str("event_type", event_type)
    who = _require_non_empty_str("actor", actor)

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
