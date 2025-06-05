# tbot_bot/reporting/status_logger.py
# Writes status.json for web interface sync
# --------------------------------------------------

import os
import json
from datetime import datetime
from tbot_bot.runtime.status_bot import bot_status
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

STATUS_FILE = get_output_path("summaries", "status.json")

def write_status():
    """Serializes the current bot_status into JSON for UI/monitoring."""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    status_data = bot_status.to_dict()
    status_data["written_at"] = datetime.utcnow().isoformat()

    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status_data, f, indent=2)
        log_event("status_logger", f"Status written to {STATUS_FILE}")
    except Exception as e:
        log_event("status_logger", f"Failed to write status.json: {e}")

if __name__ == "__main__":
    write_status()
