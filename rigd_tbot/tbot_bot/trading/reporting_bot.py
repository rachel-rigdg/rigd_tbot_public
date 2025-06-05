# tbot_bot/trading/reporting_bot.py
# Logs trade results and routes output to accounting exporters

"""
Handles structured logging, trade summaries, and Manager.io export.
Triggered on order execution and exit.
"""

import json
import csv
import os
from tbot_bot.config.env_bot import env_config
from tbot_bot.accounting.export_manager import export_trade_to_manager
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

# Load configuration
FORCE_PAPER_EXPORT = env_config.get("FORCE_PAPER_EXPORT", False)  # Should always be False in single broker mode
ENABLE_LOGGING = env_config.get("ENABLE_LOGGING", True)
LOG_FORMAT = env_config.get("LOG_FORMAT", "json").lower()
GNC_EXPORT_MODE = env_config.get("GNC_EXPORT_MODE", "auto")
BOT_IDENTITY = env_config["BOT_IDENTITY_STRING"]

# Single mode only: export files named strictly per bot identity
history_file = f"{BOT_IDENTITY}_BOT_trade_history.{LOG_FORMAT}"
summary_file = f"{BOT_IDENTITY}_BOT_daily_summary.json"

def append_trade_log(trade_data):
    """
    Appends trade to JSON or CSV file with correct bot-scoped filename.
    """
    if not ENABLE_LOGGING:
        return

    filepath = get_output_path("trades", history_file)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    if LOG_FORMAT == "json":
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                json.dump(trade_data, f)
                f.write("\n")
        except Exception as e:
            log_event("reporting_bot", f"Failed to write JSON log: {e}")

    elif LOG_FORMAT == "csv":
        header = list(trade_data.keys())
        try:
            file_exists = os.path.exists(filepath)
            with open(filepath, "a", newline='', encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=header)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(trade_data)
        except Exception as e:
            log_event("reporting_bot", f"Failed to write CSV log: {e}")

def append_summary(summary):
    """
    Writes session summary JSON with bot-scoped filename.
    """
    if not ENABLE_LOGGING:
        return

    filepath = get_output_path("summaries", summary_file)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    except Exception as e:
        log_event("reporting_bot", f"Failed to write summary: {e}")

def export_to_manager(trade_data):
    """
    Routes trade to Manager.io ledger if GNC_EXPORT_MODE is 'auto'.
    """
    if GNC_EXPORT_MODE != "auto":
        return
    try:
        export_trade_to_manager(trade_data)
        log_event("reporting_bot", f"Trade exported to Manager.io ledger")
    except Exception as e:
        log_event("reporting_bot", f"Manager.io export failed: {e}")

def finalize_trade(trade_data):
    """
    Logs and exports a trade.
    """
    trade_data["timestamp"] = utc_now().isoformat()
    append_trade_log(trade_data)
    export_to_manager(trade_data)
