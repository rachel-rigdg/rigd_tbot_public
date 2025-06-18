# tbot_bot/screeners/universe_logger.py
# Dedicated logger for all universe cache and screener symbol universe operations.
# Comprehensive, UTC timestamped, file+console output, audit-level per specification.

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Log file location (relative to project root)
def get_universe_log_path():
    # Writes to output/screeners/universe_ops.log
    from tbot_bot.support.path_resolver import resolve_universe_cache_path
    # Use the same folder as the universe cache file
    cache_path = resolve_universe_cache_path()
    log_dir = Path(cache_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir / "universe_ops.log")

class UTCFormatter(logging.Formatter):
    converter = lambda *args: datetime.now(tz=timezone.utc).timetuple()
    def formatTime(self, record, datefmt=None):
        dt = datetime.utcfromtimestamp(record.created).replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def get_universe_logger():
    log_path = get_universe_log_path()
    logger = logging.getLogger("universe_logger")
    if getattr(logger, "_initialized", False):
        return logger
    logger.setLevel(logging.INFO)
    # File Handler
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.INFO)
    fh.setFormatter(UTCFormatter("[%(asctime)s][%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    # Console Handler (optional for development)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(UTCFormatter("[%(asctime)s][%(levelname)s] %(message)s"))
    logger.addHandler(ch)
    logger._initialized = True
    return logger

def log_universe_event(event: str, details: dict = None, level: str = "info"):
    """
    Logs a universe event with structured audit detail.
    """
    logger = get_universe_logger()
    msg = f"{event}"
    if details:
        import json
        msg += " | " + json.dumps(details, default=str)
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)

# Usage example:
# log_universe_event("universe_build_started", {"exchanges": ["NYSE", "NASDAQ"]})
# log_universe_event("universe_build_complete", {"count": 1856, "path": "/output/screeners/symbol_universe.json"})
# log_universe_event("universe_cache_load_error", {"reason": "stale cache"}, level="error")
