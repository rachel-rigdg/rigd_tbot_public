# tbot_bot/trading/reporting_bot.py
# Logs trade results and routes output to accounting exporters

"""
Handles structured logging, trade summaries, and Manager.io export.
Triggered on order execution and exit.
"""

import json
import csv
import os
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.accounting.export_manager import export_trade_to_manager
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.support.utils_identity import get_bot_identity
from pathlib import Path

config = get_bot_config()
FORCE_PAPER_EXPORT = config.get("FORCE_PAPER_EXPORT", False)
ENABLE_LOGGING = config.get("ENABLE_LOGGING", True)
LOG_FORMAT = config.get("LOG_FORMAT", "json").lower()
GNC_EXPORT_MODE = config.get("GNC_EXPORT_MODE", "auto")
BOT_IDENTITY = get_bot_identity()

CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

history_file = f"{BOT_IDENTITY}_BOT_trade_history.{LOG_FORMAT}"
summary_file = f"{BOT_IDENTITY}_BOT_daily_summary.json"

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def append_trade_log(trade_data):
    """
    Appends trade to JSON or CSV file with correct bot-scoped filename.
    Skips actual logging if TEST_MODE active.
    """
    if not ENABLE_LOGGING or is_test_mode_active():
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
    Skips writing if TEST_MODE active.
    """
    if not ENABLE_LOGGING or is_test_mode_active():
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
    Skips export if TEST_MODE active.
    """
    if GNC_EXPORT_MODE != "auto" or is_test_mode_active():
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
