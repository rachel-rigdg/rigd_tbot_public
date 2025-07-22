# tbot_bot/support/utils_log.py
# Provides event logging and structured output utilities.
# All logs are disk-persistent, audit-compliant, and survive bootstrap/config errors.

import json
from pathlib import Path
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_config import get_bot_config
# Do NOT import get_output_path globally to avoid circular import
import re

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
    If config is missing or corrupt, defaults to 'info', True, 'json'.
    """
    try:
        config = get_bot_config()
        debug = str(config.get("DEBUG_LOG_LEVEL", "quiet")).lower()
        enable = config.get("ENABLE_LOGGING", True)
        fmt = str(config.get("LOG_FORMAT", "json")).lower()
        return debug, enable, fmt
    except Exception:
        return "info", True, "json"

def sanitize_filename(filename: str, max_length=100):
    """
    Sanitizes and truncates filename to avoid filesystem errors.
    Removes or replaces unsafe characters and limits length.
    """
    filename = re.sub(r"[^\w\-_\. ]", "_", filename)
    if len(filename) > max_length:
        filename = filename[:max_length]
    return filename

def get_logger(module_name: str):
    """
    Returns a bound logger object for the given module.
    Supports: .info(), .debug(), .error(), .warn(), .warning()
    """
    class BoundLogger:
        def info(self, message, extra=None):
            log_event(module_name, message, level="info", extra=extra)
        def debug(self, message, extra=None):
            log_event(module_name, message, level="debug", extra=extra)
        def error(self, message, extra=None):
            log_event(module_name, message, level="error", extra=extra)
        def warn(self, message, extra=None):
            log_event(module_name, message, level="warning", extra=extra)
        def warning(self, message, extra=None):
            self.warn(message, extra=extra)
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

    level = (level or "info").lower()
    # QUIET: Only errors/critical allowed
    if DEBUG_LOG_LEVEL == "quiet" and level not in ("error", "critical"):
        return
    # INFO: Only info/warning/error/critical allowed (not debug)
    if DEBUG_LOG_LEVEL == "info" and level == "debug":
        return
    # DEBUG: All logs allowed

    # Sanitize module name for filename safety
    safe_module_name = sanitize_filename(module)

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
        log_path = get_output_path(category="logs", filename=f"{safe_module_name}.log")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

        if LOG_FORMAT == "json":
            line = json.dumps(log_entry, ensure_ascii=False)
        else:
            line = f"[{log_entry['timestamp']}] {level.upper()} - {module}: {message}"
            if extra:
                line += f" | {json.dumps(extra, ensure_ascii=False)}"

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
    """
    Shorthand for debug-level logging.
    """
    log_event(module, message, level="debug")

def log_error(message: str, module: str = "error"):
    """
    Shorthand for error-level logging.
    """
    log_event(module, message, level="error")

# [STUB] Future: Log rotation, archival, or remote log push (if/when needed)
