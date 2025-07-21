# scripts/Fix_Paths.py
# Recursively correct outdated import paths in all Python source files under tbot_bot/

import os
import re

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET_DIR = os.path.join(BASE_DIR, "tbot_bot")

OLD_PATHS = {
    r"from tbot_bot\.env_bot": "from tbot_bot.config.env_bot",
    r"from tbot_bot\.orders_bot": "from tbot_bot.trading.orders_bot",
    r"from tbot_bot\.logs_bot": "from tbot_bot.trading.logs_bot",
}

def fix_imports(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    original_content = content
    for old, new in OLD_PATHS.items():
        content = re.sub(old, new, content)

    if content != original_content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated: {file_path}")

def scan_and_fix(directory):
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".py"):
                full_path = os.path.join(root, filename)
                fix_imports(full_path)

if __name__ == "__main__":
    scan_and_fix(TARGET_DIR)
