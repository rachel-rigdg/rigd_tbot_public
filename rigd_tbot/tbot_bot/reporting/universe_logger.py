# tbot_bot/reporting/universe_logger.py
# Dedicated logger for all universe cache, blocklist, and screener symbol universe operations.
# Comprehensive, UTC timestamped, file+console output, audit-level per specification.
# All logs written to tbot_bot/output/screeners/universe_ops.log

import logging
import sys
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

def get_universe_log_path() -> str:
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
        dt = datetime.utcfromtimestamp(record.created).replace(tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

class JSONAuditFileHandler(logging.Handler):
    """
    Append-only JSONL audit handler.
    Each record is a single JSON object per line with fields:
      ts, level, event, details
    Enforces append-only by opening with O_APPEND on each emit.
    """
    def __init__(self, log_path: str):
        super().__init__(level=logging.INFO)
        self.log_path = log_path
        # Ensure directory exists
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.utcfromtimestamp(record.created).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            # Message convention: "EVENT | {json details}" or just "EVENT"
            event = record.getMessage()
            details: Optional[Dict[str, Any]] = None
            # If message contains a JSON tail after ' | ', try to parse it
            if " | " in event:
                evt, tail = event.split(" | ", 1)
                event = evt
                try:
                    details = json.loads(tail)
                except Exception:
                    details = {"raw": tail}
            audit = {
                "ts": ts,
                "level": record.levelname.lower(),
                "event": event,
                "details": details,
            }
            line = json.dumps(audit, ensure_ascii=False, separators=(",", ":")) + "\n"
            # Append-only write with fsync
            fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            # Never raise from logging
            self.handleError(record)

def get_universe_logger() -> logging.Logger:
    """
    Initializes and returns a singleton logger instance for universe operations.
    Logs to file (JSONL append-only) and console (human-readable) with UTC timestamps.
    Prevents duplicate handlers.
    """
    log_path = get_universe_log_path()
    logger = logging.getLogger("universe_logger")
    if getattr(logger, "_initialized", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers = []

    # Append-only JSON audit file
    json_handler = JSONAuditFileHandler(log_path)
    logger.addHandler(json_handler)

    # Human-readable console
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
        try:
            msg += " | " + json.dumps(details, default=str, ensure_ascii=False)
        except Exception as e:
            msg += f" | " + json.dumps({"_serialize_error": str(e)}, ensure_ascii=False)
    lvl = (level or "info").lower()
    if lvl == "error":
        logger.error(msg)
    elif lvl == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)
