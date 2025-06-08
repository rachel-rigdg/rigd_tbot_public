# tbot_bot/support/utils_log.py
# Provides event logging and structured output utilities

import json
from pathlib import Path
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_config import get_bot_config

def get_log_dir():
    """
    Dynamically resolve the log directory using the current bot identity.
    Fallback to 'bootstrap' log dir if identity is missing or get_bot_identity import fails.
    """
    try:
        BASE_DIR = Path(__file__).resolve().parents[2]
    except Exception:
        from os import getcwd
        BASE_DIR = Path(getcwd())
    try:
        from tbot_bot.support.utils_identity import get_bot_identity
        BOT_IDENTITY = get_bot_identity()
        if not BOT_IDENTITY or BOT_IDENTITY.upper() == "UNKNOWN_BOT":
            BOT_IDENTITY = "bootstrap"
    except Exception:
        BOT_IDENTITY = "bootstrap"
    return BASE_DIR / "tbot_bot" / "output" / BOT_IDENTITY / "logs"

def get_log_settings():
    """
    Returns (DEBUG_LOG_LEVEL, ENABLE_LOGGING, LOG_FORMAT) from bot config, safe fallback.
    """
    config = get_bot_config()
    debug = str(config.get("DEBUG_LOG_LEVEL", "quiet")).lower()
    enable = config.get("ENABLE_LOGGING", True)
    fmt = str(config.get("LOG_FORMAT", "json")).lower()
    return debug, enable, fmt

def log_event(module: str, message: str, level: str = "info", extra: dict = None):
    """
    Logs runtime events to disk and prints to stdout.
    Bootstrap safe: Will always print to stdout even if config/log dir missing.
    """
    DEBUG_LOG_LEVEL, ENABLE_LOGGING, LOG_FORMAT = get_log_settings()
    if not ENABLE_LOGGING:
        return

    level = level.lower()
    if DEBUG_LOG_LEVEL == "quiet" and level not in ("error", "critical"):
        return
    if DEBUG_LOG_LEVEL == "info" and level == "debug":
        return

    log_entry = {
        "timestamp": utc_now().isoformat(),
        "module": module,
        "level": level,
        "message": message
    }

    if extra:
        log_entry["extra"] = extra

    try:
        LOG_DIR = get_log_dir()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        filepath = LOG_DIR / f"{module}.log"

        if LOG_FORMAT == "json":
            line = json.dumps(log_entry)
        else:
            line = f"[{log_entry['timestamp']}] {level.upper()} - {module}: {message}"
            if extra:
                line += f" | {json.dumps(extra)}"

        with open(filepath, "a") as f:
            f.write(line + "\n")

        print(line)

    except Exception as e:
        # Always print, even if writing to file fails
        print(f"[utils_log] ERROR: Failed to write log entry. {e}")
        print(f"[utils_log] Original log attempt: {log_entry}")

def log_debug(message: str, module: str = "debug"):
    log_event(module, message, level="debug")

def log_error(message: str, module: str = "error"):
    log_event(module, message, level="error")
