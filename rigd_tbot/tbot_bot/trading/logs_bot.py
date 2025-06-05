# tbot_bot/trading/logs_bot.py
# Runtime trade + session logging

"""
Handles logging of trade and strategy activity into JSON or CSV files.
Conforms to single-broker spec with all paths derived from identity metadata.
"""

import os
import json
import csv
from datetime import datetime
from tbot_bot.config.env_bot import env_config
from tbot_bot.support.path_resolver import get_output_path

LOG_FORMAT = env_config.get("LOG_FORMAT", "json").lower()
ENABLE_LOGGING = env_config.get("ENABLE_LOGGING", True)
BOT_ID = env_config["BOT_IDENTITY_STRING"]

# ----------------------------
# TRADE LOGGING
# ----------------------------

def log_trade(trade_record: dict):
    """
    Append a trade record to the bot's trade history log file (CSV or JSON lines).
    """
    if not ENABLE_LOGGING:
        return

    path = get_output_path("trades", f"{BOT_ID}_BOT_trade_history.{LOG_FORMAT}")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        if LOG_FORMAT == "json":
            with open(path, "a") as f:
                f.write(json.dumps(trade_record) + "\n")

        elif LOG_FORMAT == "csv":
            write_header = not os.path.exists(path)
            with open(path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=trade_record.keys())
                if write_header:
                    writer.writeheader()
                writer.writerow(trade_record)

    except Exception as e:
        print(f"[logs_bot] Failed to write trade record: {e}")

# ----------------------------
# GENERIC EVENT LOGGING
# ----------------------------

def log_event(source: str, message: str):
    """
    Logs runtime event with timestamp to stdout and strategy-specific log file.
    """
    if not ENABLE_LOGGING:
        return

    timestamp = datetime.utcnow().isoformat()
    log_line = f"[{timestamp}] [{source}] {message}"
    print(log_line)

    path = get_output_path("logs", f"{source}.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "a") as f:
            f.write(log_line + "\n")
    except Exception as e:
        print(f"[logs_bot] Failed to write event log: {e}")
