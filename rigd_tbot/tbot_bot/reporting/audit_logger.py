# tbot_bot/reporting/audit_logger.py 
#  Support structured logs for holdings management actions.

import os
import json
from datetime import datetime
from tbot_bot.support import path_resolver

LOG_FILE = path_resolver.resolve_output_path("logs/holdings_audit.log")

def log_holdings_event(event_type, message, extra=None):
    log_dir = os.path.dirname(LOG_FILE)
    os.makedirs(log_dir, exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "message": message,
    }
    if extra and isinstance(extra, dict):
        record.update(extra)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
