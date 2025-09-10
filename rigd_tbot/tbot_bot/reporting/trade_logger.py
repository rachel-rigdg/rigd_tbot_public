# tbot_bot/reporting/trade_logger.py
# append_trade(trade: dict) → writes to JSON/CSV under /output/trades/
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.

import sys

if __name__ == "__main__":
    print("[trade_logger.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import os
import json
import csv
from datetime import datetime
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path
from datetime import datetime, timezone
print(f"[LAUNCH] trade_logger.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

# Load config
config = get_bot_config()
BOT_IDENTITY = config.get("BOT_IDENTITY_STRING")
LOG_FORMAT = config.get("LOG_FORMAT", "json").lower()
ENABLE_LOGGING = config.get("ENABLE_LOGGING", True)

def append_trade(trade: dict):
    """
    Writes trade entry to identity-scoped /output/trades/ directory
    as JSON or CSV, with compliant naming.
    """
    if not ENABLE_LOGGING:
        return

    base_filename = f"{BOT_IDENTITY}_BOT_trade_history"
    json_filepath = get_output_path("trades", f"{base_filename}.json")
    csv_filepath = get_output_path("trades", f"{base_filename}.csv")
    os.makedirs(os.path.dirname(json_filepath), exist_ok=True)

    try:
        if LOG_FORMAT == "json":
            with open(json_filepath, "a") as f:
                json.dump(trade, f)
                f.write("\n")
            log_event("trade_logger", f"Appended trade to {json_filepath}")
        elif LOG_FORMAT == "csv":
            write_header = not os.path.exists(csv_filepath)
            with open(csv_filepath, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=trade.keys())
                if write_header:
                    writer.writeheader()
                writer.writerow(trade)
            log_event("trade_logger", f"Appended trade to {csv_filepath}")
    except Exception as e:
        log_event("trade_logger", f"Failed to write trade: {e}", level="error")
