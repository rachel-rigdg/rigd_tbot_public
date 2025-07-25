# tbot_bot/test/test_logging_format.py
# Ensures all log entries follow required format and completeness
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
import unittest
import os
import re
import time
from pathlib import Path
from tbot_bot.support.path_resolver import get_output_path, resolve_control_path
from tbot_bot.support.utils_log import log_event

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_logging_format.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
LOGFILE = get_output_path("logs", "test_mode.log")
MAX_TEST_TIME = 90  # seconds per test

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_logging_format", msg, logfile=LOGFILE)
    except Exception:
        pass

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_logging_format.py] Individual test flag not present. Exiting.")
        sys.exit(1)

LOG_DIR = get_output_path("logs")
LOG_FILE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[[A-Z]+\] .+")

class TestLoggingFormat(unittest.TestCase):
    def setUp(self):
        self.log_files = [
            "open.log",
            "mid.log",
            "close.log",
            "unresolved_orders.log",
            "error_tracebacks.log"
        ]
        self.log_paths = [os.path.join(LOG_DIR, f) for f in self.log_files]

    def test_logs_exist_and_not_empty(self):
        for path in self.log_paths:
            with self.subTest(log_file=path):
                if not os.path.exists(path):
                    safe_print(f"[test_logging_format] Log file does not exist: {path}")
                self.assertTrue(os.path.exists(path), f"Log file does not exist: {path}")
                if os.path.getsize(path) == 0:
                    safe_print(f"[test_logging_format] Log file is empty: {path}")
                self.assertGreater(os.path.getsize(path), 0, f"Log file is empty: {path}")

    def test_log_format(self):
        for path in self.log_paths:
            with self.subTest(log_file=path):
                with open(path, "r", encoding="utf-8") as f:
                    for line_number, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        if not LOG_FILE_PATTERN.match(line):
                            safe_print(f"[test_logging_format] Log line {line_number} in {path} does not match format: {line}")
                        self.assertRegex(
                            line,
                            LOG_FILE_PATTERN,
                            f"Log line {line_number} in {path} does not match format: {line}"
                        )

def run_test():
    start_time = time.time()
    try:
        import unittest as _unittest
        ret = _unittest.main([__file__])
        result = "PASSED" if ret == 0 else "ERRORS"
    except Exception as e:
        result = "ERRORS"
        safe_print(f"[test_logging_format.py] Exception: {e}")
    elapsed = time.time() - start_time
    if elapsed > MAX_TEST_TIME:
        safe_print(f"[test_logging_format.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
        result = "ERRORS"
    safe_print(f"[test_logging_format.py] FINAL RESULT: {result}")
    if Path(TEST_FLAG_PATH).exists():
        Path(TEST_FLAG_PATH).unlink()

if __name__ == "__main__":
    run_test()
