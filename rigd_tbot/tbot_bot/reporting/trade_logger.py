# tbot_bot/reporting/trade_logger.py
# append_trade(trade: dict) → writes to JSON/CSV under /output/trades/
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.

import os
import sys

# Block direct CLI runs; allow when launched by the supervisor (env flag set in launch_registry.spawn_module).
if __name__ == "__main__" and not os.environ.get("TBOT_LAUNCHED_BY_SUPERVISOR"):
    print("[trade_logger.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import json
import csv
import time
from datetime import datetime, timezone
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

# Load config
config = get_bot_config()
BOT_IDENTITY = config.get("BOT_IDENTITY_STRING") or "UNKNOWN_IDENTITY"
LOG_FORMAT = str(config.get("LOG_FORMAT", "json")).lower()
ENABLE_LOGGING = bool(config.get("ENABLE_LOGGING", True))

def append_trade(trade: dict):
    """
    Writes trade entry to identity-scoped /output/trades/ directory
    as JSON or CSV, with compliant naming.
    """
    if not ENABLE_LOGGING or not isinstance(trade, dict):
        return

    base_filename = f"{BOT_IDENTITY}_BOT_trade_history"
    json_filepath = get_output_path("trades", f"{base_filename}.json")
    csv_filepath = get_output_path("trades", f"{base_filename}.csv")
    os.makedirs(os.path.dirname(json_filepath), exist_ok=True)

    try:
        if LOG_FORMAT == "json":
            with open(json_filepath, "a", encoding="utf-8") as f:
                json.dump(trade, f)
                f.write("\n")
            log_event("trade_logger", f"Appended trade to {json_filepath}")
        elif LOG_FORMAT == "csv":
            write_header = not os.path.exists(csv_filepath)
            with open(csv_filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(trade.keys()))
                if write_header:
                    writer.writeheader()
                writer.writerow(trade)
            log_event("trade_logger", f"Appended trade to {csv_filepath}")
        else:
            # Fallback to JSON if an unknown format is configured
            with open(json_filepath, "a", encoding="utf-8") as f:
                json.dump(trade, f)
                f.write("\n")
            log_event("trade_logger", f"[fallback] Appended trade to {json_filepath}")
    except Exception as e:
        log_event("trade_logger", f"Failed to write trade: {e}", level="error")


# When launched by the supervisor, run as a lightweight persistent service to avoid restart thrash.
if __name__ == "__main__":
    print(f"[LAUNCH] trade_logger.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)
    log_event("trade_logger", "Trade logger service started (idle; writes occur via append_trade calls).")
    # Idle loop with a very light heartbeat; adjust via LOG_HEARTBEAT_SEC if desired.
    heartbeat = int(config.get("LOG_HEARTBEAT_SEC", 3600))
    while True:
        try:
            log_event("trade_logger", "heartbeat")
        except Exception:
            # Never crash the service due to logging errors.
            pass
        time.sleep(max(heartbeat, 60))
