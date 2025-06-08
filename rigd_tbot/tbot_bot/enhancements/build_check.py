# tbot_bot/enhancements/build_check.py
# Validates presence of required files and config before launch
# ------------------------------------------------------
# Pre-launch verifier to ensure all critical files, folders, and configs exist.
# Called during startup by main_bot.py

import os
import sys
from pathlib import Path
from tbot_bot.support.path_resolver import get_bot_identity, get_output_path

REQUIRED_FILES = [
    ".env",
    "tbot_bot/support/.env_bot.enc",
    "tbot_bot/config/env_bot.py",
    "tbot_bot/accounting/tradebot_exporter.py",
    "tbot_bot/accounting/account_transaction.py",
    "tbot_bot/accounting/accounting_config.py"
]

REQUIRED_FOLDERS = [
    "backups/"
]

def build_required_log_files():
    bot_identity = get_bot_identity()
    return [
        get_output_path(bot_identity, "logs", "open.log"),
        get_output_path(bot_identity, "logs", "mid.log"),
        get_output_path(bot_identity, "logs", "close.log"),
        get_output_path(bot_identity, "logs", "unresolved_orders.log"),
        get_output_path(bot_identity, "logs", "error_tracebacks.log"),
    ]

def check_file_exists(path):
    return Path(path).is_file()

def check_folder_exists(path):
    return Path(path).is_dir()

def run_build_check():
    errors = []

    for file in REQUIRED_FILES:
        if not check_file_exists(file):
            errors.append(f"Missing required file: {file}")

    for folder in REQUIRED_FOLDERS:
        if not check_folder_exists(folder):
            errors.append(f"Missing required folder: {folder}")

    for log_file in build_required_log_files():
        if not check_file_exists(log_file):
            try:
                os.makedirs(Path(log_file).parent, exist_ok=True)
                with open(log_file, "w") as f:
                    f.write("")
            except Exception as e:
                errors.append(f"Failed to create placeholder log: {log_file} ({e})")

    if errors:
        print("BUILD CHECK FAILED:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    else:
        print("BUILD CHECK PASSED — all critical files and folders found.")

if __name__ == "__main__":
    run_build_check()
