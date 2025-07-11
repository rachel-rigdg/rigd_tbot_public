# tbot_bot/screeners/universe_logger.py
# Dedicated logger for all universe cache, blocklist, and screener symbol universe operations.
# Comprehensive, UTC timestamped, file+console output, audit-level per specification.
# Used for /stock/symbol, /stock/profile2, /quote, blocklist events, staged builds, archiving, rechecks.
# All logs written to tbot_bot/output/screeners/universe_ops.log

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

def get_universe_log_path():
    """
    Resolves log file path for universe operations.
    Ensures output directory exists.
    """
    from tbot_bot.support.path_resolver import resolve_universe_log_path
    log_path = resolve_universe_log_path()
    log_dir = Path(log_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_path)

class UTCFormatter(logging.Formatter):
    """
    Formatter that prints UTC ISO timestamps for log records.
    """
    converter = lambda *args: datetime.now(tz=timezone.utc).timetuple()
    def formatTime(self, record, datefmt=None):
        dt = datetime.utcfromtimestamp(record.created).replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def get_universe_logger():
    """
    Initializes and returns a singleton logger instance for universe operations.
    Logs to file and console with UTC timestamps and audit-level info.
    Prevents duplicate handlers.
    """
    log_path = get_universe_log_path()
    logger = logging.getLogger("universe_logger")
    if getattr(logger, "_initialized", False):
        return logger

    logger.setLevel(logging.INFO)
    # Remove any old handlers first to avoid log duplication
    logger.handlers = []

    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.INFO)
    fh.setFormatter(UTCFormatter("[%(asctime)s][%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(UTCFormatter("[%(asctime)s][%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    logger._initialized = True
    return logger

def log_universe_event(event: str, details: dict = None, level: str = "info"):
    """
    Logs a universe/blocklist/staged build event with structured audit detail.
    Used for all universe, blocklist, staged, recovery, and archiving operations.
    Includes event name and optional JSON-serializable details dict.
    Supports 'info', 'warning', and 'error' log levels.
    """
    logger = get_universe_logger()
    msg = f"{event}"
    if details:
        import json
        try:
            msg += " | " + json.dumps(details, default=str, ensure_ascii=False)
        except Exception as e:
            msg += f" | [Failed to serialize details: {e}]"
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)
