# tbot_bot/reporting/status_logger.py
# WORKER. Only invoked to write session status summary for archival/accounting.
# Writes output/{bot_id}/summaries/status.json only (never writes or touches output/logs/status.json).
# Never runs as a watcher/daemon, never started except by main.py or strategy completion.

import os
import json
from datetime import datetime
from tbot_bot.runtime.status_bot import bot_status
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import resolve_status_summary_path, get_bot_identity

BOT_IDENTITY = get_bot_identity()
SUMMARY_STATUS_FILE = resolve_status_summary_path(BOT_IDENTITY)

def write_status():
    """Serializes the current bot_status into JSON for archival/accounting summary only."""
    status_data = bot_status.to_dict()
    status_data["written_at"] = datetime.utcnow().isoformat()
    os.makedirs(os.path.dirname(SUMMARY_STATUS_FILE), exist_ok=True)
    try:
        with open(SUMMARY_STATUS_FILE, "w") as f:
            json.dump(status_data, f, indent=2)
        log_event("status_logger", f"Status written to {SUMMARY_STATUS_FILE}")
    except Exception as e:
        log_event("status_logger", f"Failed to write status.json to {SUMMARY_STATUS_FILE}: {e}")

if __name__ == "__main__":
    write_status()
