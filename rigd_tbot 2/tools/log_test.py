# tools/log_test.py
# Verifies log file creation in the runtime environment

from pathlib import Path

base_dir = Path.cwd()  # Use CWD for safe runtime path resolution
log_dir = base_dir / "logs" / "bot" / "paper"
test_file = log_dir / "test_log.log"

try:
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(test_file, "a") as f:
        f.write("Log test successful.\n")
    print(f"SUCCESS: Log written to {test_file}")
except Exception as e:
    print(f"FAILURE: {e}")
