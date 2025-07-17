# tbot_bot/test/test_logging_format.py
# Ensures all log entries follow required format and completeness
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
import unittest
import os
import re
from pathlib import Path
from tbot_bot.support.path_resolver import get_output_path

TEST_FLAG_PATH = get_output_path("control", "test_mode_logging_format.flag")
RUN_ALL_FLAG = get_output_path("control", "test_mode.flag")

def safe_print(msg):
    try:
        print(msg, flush=True)
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
                self.assertTrue(os.path.exists(path), f"Log file does not exist: {path}")
                self.assertGreater(os.path.getsize(path), 0, f"Log file is empty: {path}")

    def test_log_format(self):
        for path in self.log_paths:
            with self.subTest(log_file=path):
                with open(path, "r", encoding="utf-8") as f:
                    for line_number, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        self.assertRegex(
                            line,
                            LOG_FILE_PATTERN,
                            f"Log line {line_number} in {path} does not match format: {line}"
                        )

def run_test():
    import unittest as _unittest
    ret = _unittest.main([__file__])
    if Path(TEST_FLAG_PATH).exists():
        Path(TEST_FLAG_PATH).unlink()
    if ret == 0:
        safe_print("[test_logging_format.py] TEST PASSED")
    else:
        safe_print(f"[test_logging_format.py] TEST FAILED (code={ret})")

if __name__ == "__main__":
    run_test()
