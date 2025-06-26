# tbot_bot/reporting/session_report.py
# Generates final report for each trading session
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.

import sys

if __name__ == "__main__":
    print("[session_report.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import os
import json
from datetime import datetime
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

identity = get_bot_identity()  # {ENTITY}_{JURIS}_{BROKER}_{BOT_ID}
summary_filename = f"{identity}_BOT_daily_summary.json"
timestamped_filename = f"summary_{identity}_BOT_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

# Paths
SUMMARY_INPUT = get_output_path("summaries", summary_filename)
SUMMARY_ARCHIVE = get_output_path("summaries", timestamped_filename)

def generate_session_report():
    """Loads the in-session summary file and archives a timestamped copy."""
    os.makedirs(os.path.dirname(SUMMARY_ARCHIVE), exist_ok=True)

    if not os.path.exists(SUMMARY_INPUT):
        log_event("session_report", f"No session summary found: {SUMMARY_INPUT}")
        return False

    try:
        with open(SUMMARY_INPUT, "r") as f:
            data = json.load(f)

        with open(SUMMARY_ARCHIVE, "w") as f:
            json.dump(data, f, indent=2)

        log_event("session_report", f"Session report archived to {SUMMARY_ARCHIVE}")
        return True
    except Exception as e:
        log_event("session_report", f"Failed to generate session report: {e}")
        return False
