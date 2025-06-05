# tbot_bot/reporting/log_rotation.py
# rotate_logs(retention_days: int = 7) → clean up output/logs, trades, summaries for current bot identity

import os
import time
from datetime import datetime
from tbot_bot.config.env_bot import env_config
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

BOT_IDENTITY = env_config.get("BOT_IDENTITY_STRING")

CATEGORIES = ["logs", "summaries", "trades"]

def rotate_logs(retention_days: int = 7):
    """
    Deletes files older than retention_days in bot-scoped logs, summaries, and trades.
    Does NOT touch ledgers.
    """
    cutoff = time.time() - (retention_days * 86400)
    deleted = 0
    scanned = 0

    for category in CATEGORIES:
        base_dir = get_output_path(bot_identity=BOT_IDENTITY, category=category, filename="", output_subdir=True)
        if not os.path.isdir(base_dir):
            continue

        for root, _, files in os.walk(base_dir):
            for file in files:
                full_path = os.path.join(root, file)
                try:
                    if os.path.isfile(full_path):
                        scanned += 1
                        if os.path.getmtime(full_path) < cutoff:
                            os.remove(full_path)
                            log_event("log_rotation", f"Deleted: {full_path}")
                            deleted += 1
                except Exception as e:
                    log_event("log_rotation", f"Failed to delete {full_path}: {e}", level="error")

    log_event("log_rotation", f"Rotation complete: scanned={scanned}, deleted={deleted}, retention={retention_days}d")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prune logs, trades, and summaries older than N days.")
    parser.add_argument("--days", type=int, default=7, help="Retention period in days (default = 7)")
    args = parser.parse_args()
    rotate_logs(retention_days=args.days)
