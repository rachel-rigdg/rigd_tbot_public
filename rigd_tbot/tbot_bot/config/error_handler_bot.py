# tbot_bot/config/error_handler_bot.py
# Centralized exception manager and classified logging for tbot

import traceback
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from tbot_bot.trading.notifier_bot import notify_critical_error
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path

# Load configuration at runtime (never at module import for bootstrap safety)
config = get_bot_config()
LOG_FORMAT = config.get("LOG_FORMAT", "json")

# Use new path_resolver logic, always require both category and filename
LOG_FILE = get_output_path(category="logs", filename="unresolved_orders.log")

ERROR_CATEGORIES = ["NetworkError", "BrokerError", "LogicError", "ConfigError"]

def log_error(error_type, strategy_name, broker, exception, error_code=None):
    """
    Logs error in a structured format and sends alert if necessary.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    trace = traceback.format_exc(limit=5)

    log_data = {
        "timestamp": timestamp,
        "strategy_name": strategy_name,
        "broker": broker,
        "error_type": error_type,
        "error_code": error_code,
        "raw_exception": str(exception),
        "stack_trace": trace
    }

    # Verbose shell logging
    print("[error_handler_bot] ERROR LOG ENTRY:", file=sys.stderr)
    for k, v in log_data.items():
        print(f"    {k}: {v}", file=sys.stderr)

    try:
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            if LOG_FORMAT == "json":
                import json
                f.write(json.dumps(log_data) + "\n")
            else:
                f.write(
                    f"{timestamp},{strategy_name},{broker},{error_type},{error_code},{exception}\n"
                )
    except Exception as log_exc:
        print("[error_handler_bot] Failed to write to log:", log_exc, file=sys.stderr)

    if error_type in ["BrokerError", "NetworkError", "ConfigError"]:
        notify_critical_error(
            summary=f"Critical {error_type} in {strategy_name}",
            detail=f"{timestamp}\n\nError: {exception}\n\nTrace:\n{trace}"
        )

def handle(exception, strategy_name="unknown", broker="unknown", category="LogicError", error_code=None):
    """
    Public entry point for other modules to call when an error occurs.
    """
    if category not in ERROR_CATEGORIES:
        category = "LogicError"
    log_error(category, strategy_name, broker, exception, error_code)
