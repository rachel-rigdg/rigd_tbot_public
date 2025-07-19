# tbot_bot/support/utils_log.py
# Provides event logging and structured output utilities

import json
from pathlib import Path
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_config import get_bot_config
# Do NOT import get_output_path globally to avoid circular import

def get_log_dir():
    """
    Returns the global/system logs directory.
    Always resolves to /output/logs/ for system logs (never per-identity).
    """
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "tbot_bot" / "output" / "logs"

def get_log_settings():
    """
    Returns (DEBUG_LOG_LEVEL, ENABLE_LOGGING, LOG_FORMAT) from bot config, safe fallback.
    """
    config = get_bot_config()
    debug = str(config.get("DEBUG_LOG_LEVEL", "quiet")).lower()
    enable = config.get("ENABLE_LOGGING", True)
    fmt = str(config.get("LOG_FORMAT", "json")).lower()
    return debug, enable, fmt

def get_logger(module_name: str):
    """
    Returns a bound logger function for the given module.
    Supports: .info(), .debug(), .error()
    """
    class BoundLogger:
        def info(self, message, extra=None):
            log_event(module_name, message, level="info", extra=extra)
        def debug(self, message, extra=None):
            log_event(module_name, message, level="debug", extra=extra)
        def error(self, message, extra=None):
            log_event(module_name, message, level="error", extra=extra)
    return BoundLogger()

def log_event(module: str, message: str, level: str = "info", extra: dict = None):
    """
    Logs runtime events to disk and prints to stdout.
    Always writes to /output/logs/{module}.log regardless of bot identity.
    Bootstrap safe: Will always print to stdout even if config/log dir missing.
    """
    DEBUG_LOG_LEVEL, ENABLE_LOGGING, LOG_FORMAT = get_log_settings()
    if not ENABLE_LOGGING:
        return

    level = level.lower()
    # QUIET: Only errors/critical allowed
    if DEBUG_LOG_LEVEL == "quiet" and level not in ("error", "critical"):
        return
    # INFO: Only info/warning/error/critical allowed (not debug)
    if DEBUG_LOG_LEVEL == "info" and level == "debug":
        return
    # DEBUG: All logs allowed

    log_entry = {
        "timestamp": utc_now().isoformat(),
        "module": module,
        "level": level,
        "message": message
    }

    if extra:
        log_entry["extra"] = extra

    try:
        # Import here to avoid circular import at module level
        from tbot_bot.support.path_resolver import get_output_path
        log_path = get_output_path(category="logs", filename=f"{module}.log")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

        if LOG_FORMAT == "json":
            line = json.dumps(log_entry)
        else:
            line = f"[{log_entry['timestamp']}] {level.upper()} - {module}: {message}"
            if extra:
                line += f" | {json.dumps(extra)}"

        # Only print to stdout if not quiet or is error/critical
        if not (DEBUG_LOG_LEVEL == "quiet" and level not in ("error", "critical")):
            print(line)

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    except Exception as e:
        # Always print, even if writing to file fails
        print(f"[utils_log] ERROR: Failed to write log entry. {e}")
        print(f"[utils_log] Original log attempt: {log_entry}")

def log_debug(message: str, module: str = "debug"):
    log_event(module, message, level="debug")

def log_error(message: str, module: str = "error"):
    log_event(module, message, level="error")
