# tbot_bot/reporting/status_logger.py
# Writes status.json for web interface sync and logging archive
# --------------------------------------------------

import os
import json
from datetime import datetime
from tbot_bot.runtime.status_bot import bot_status, STATUS_FILE_PATH
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

SUMMARY_STATUS_FILE = get_output_path("summaries", "status.json")
LOG_STATUS_FILE = str(STATUS_FILE_PATH)

def write_status():
    """Serializes the current bot_status into JSON for UI/monitoring and logs."""
    status_data = bot_status.to_dict()
    status_data["written_at"] = datetime.utcnow().isoformat()
    for path in [SUMMARY_STATUS_FILE, LOG_STATUS_FILE]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w") as f:
                json.dump(status_data, f, indent=2)
            log_event("status_logger", f"Status written to {path}")
        except Exception as e:
            log_event("status_logger", f"Failed to write status.json to {path}: {e}")

if __name__ == "__main__":
    write_status()
