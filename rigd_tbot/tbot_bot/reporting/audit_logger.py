# tbot_bot/reporting/audit_logger.py
# Structured audit logging for all allocation, reserve, trade, and holdings management actions.
# Called from all trade logic, float/rebalance/tax/payroll, and UI override actions.

import os
import json
from datetime import datetime
from tbot_bot.support import path_resolver

def _get_audit_log_path(bot_identity=None):
    # Always resolves to output/{BOT_IDENTITY}/logs/holdings_audit.log
    try:
        return path_resolver.resolve_holdings_audit_log_path(bot_identity)
    except Exception:
        # Fallback: Use shared output/logs for bootstrap or no identity
        return path_resolver.resolve_output_path("logs/holdings_audit.log")

def audit_log_event(event_type, user=None, reference=None, details=None, bot_identity=None):
    """
    Appends a single audit event to the holdings_audit.log with UTC ISO-8601 timestamp.
    Fields:
        event_type (str): Event code or type.
        user (str): Username or 'system' if not present.
        reference (str|int): Reference code, trade/order ID, or context string.
        details (dict): Arbitrary JSON-serializable dict for full event context.
        bot_identity (str): Explicit identity string if overriding.
    """
    log_file = _get_audit_log_path(bot_identity)
    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": str(event_type),
        "user": user or "system",
        "reference": reference,
        "details": details if details is not None else {},
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def log_holdings_event(event_type, message, extra=None, bot_identity=None):
    """
    Legacy: Logs a simpler event line with message text.
    """
    log_file = _get_audit_log_path(bot_identity)
    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "message": message,
    }
    if extra and isinstance(extra, dict):
        record.update(extra)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
