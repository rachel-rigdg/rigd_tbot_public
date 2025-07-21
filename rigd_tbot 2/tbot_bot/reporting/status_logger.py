# tbot_bot/reporting/status_logger.py
# Writes status.json for archival/accounting summary only (never logs/status.json)
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.
# --------------------------------------------------

import sys

if __name__ == "__main__":
    print("[status_logger.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

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
    # Force state to match bot_state.txt on disk (always freshest)
    try:
        from pathlib import Path
        bot_state_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
        if bot_state_path.exists():
            status_data["state"] = bot_state_path.read_text(encoding="utf-8").strip()
        else:
            status_data["state"] = "unknown"
    except Exception:
        status_data["state"] = "unknown"
    os.makedirs(os.path.dirname(SUMMARY_STATUS_FILE), exist_ok=True)
    try:
        with open(SUMMARY_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)
        log_event("status_logger", f"Status written to {SUMMARY_STATUS_FILE}")
    except Exception as e:
        log_event("status_logger", f"Failed to write status.json to {SUMMARY_STATUS_FILE}: {e}")
