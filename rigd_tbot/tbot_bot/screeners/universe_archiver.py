# tbot_bot/screeners/universe_archiver.py
# Automated archival, rotation, and restore utilities for symbol universe and blocklist files.
# 100% spec-compliant with archival, retention policy, and rollback/restore logic.

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbot_bot.support.path_resolver import (
    resolve_universe_cache_path,
    resolve_universe_partial_path,
    resolve_screener_blocklist_path,
)

ARCHIVE_DIR = Path("tbot_bot/output/screeners/archive")
RETENTION_DAYS = 90  # Retain files for 90 days by default

def utc_now():
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def ensure_archive_dir():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

def archive_file(src_path, label=None):
    ensure_archive_dir()
    if not os.path.exists(src_path):
        return None
    ts = utc_now().strftime("%Y%m%dT%H%M%SZ")
    basename = os.path.basename(src_path)
    label_str = f"_{label}" if label else ""
    archive_name = f"{basename}.{ts}{label_str}.bak"
    archive_path = ARCHIVE_DIR / archive_name
    shutil.copy2(src_path, archive_path)
    return str(archive_path)

def archive_all(label=None):
    paths = [
        resolve_universe_cache_path(),
        resolve_universe_partial_path(),
        resolve_screener_blocklist_path()
    ]
    archived = []
    for path in paths:
        if os.path.exists(path):
            arch = archive_file(path, label)
            if arch:
                archived.append(arch)
    return archived

def list_archives(basename=None):
    ensure_archive_dir()
    files = []
    for f in ARCHIVE_DIR.iterdir():
        if f.is_file() and (not basename or f.name.startswith(basename)):
            files.append(str(f))
    files.sort(reverse=True)
    return files

def cleanup_archives(retention_days=RETENTION_DAYS):
    now = utc_now()
    deleted = []
    for f in ARCHIVE_DIR.iterdir():
        if not f.is_file():
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        if (now - mtime) > timedelta(days=retention_days):
            try:
                f.unlink()
                deleted.append(str(f))
            except Exception:
                pass
    return deleted

def restore_archive(archive_path, target_path):
    if not os.path.isfile(archive_path):
        raise RuntimeError(f"Archive file does not exist: {archive_path}")
    shutil.copy2(archive_path, target_path)

def latest_archive_for(basename):
    archives = list_archives(basename)
    return archives[0] if archives else None

def restore_latest_universe():
    latest = latest_archive_for("symbol_universe.json")
    if latest:
        restore_archive(latest, resolve_universe_cache_path())
        return True
    return False

def restore_latest_blocklist():
    latest = latest_archive_for("screener_blocklist.txt")
    if latest:
        restore_archive(latest, resolve_screener_blocklist_path())
        return True
    return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Universe/blocklist archival utility")
    parser.add_argument("--archive", action="store_true", help="Archive all universe/blocklist files now")
    parser.add_argument("--cleanup", action="store_true", help="Clean up old archives")
    parser.add_argument("--list", action="store_true", help="List all archive files")
    parser.add_argument("--restore-universe", action="store_true", help="Restore latest universe cache from archive")
    parser.add_argument("--restore-blocklist", action="store_true", help="Restore latest blocklist from archive")
    args = parser.parse_args()

    if args.archive:
        archived = archive_all()
        print("Archived files:", archived)
    if args.cleanup:
        deleted = cleanup_archives()
        print("Deleted old archives:", deleted)
    if args.list:
        print("All archives:")
        for f in list_archives():
            print(f)
    if args.restore_universe:
        if restore_latest_universe():
            print("Restored latest universe cache.")
        else:
            print("No universe archive found.")
    if args.restore_blocklist:
        if restore_latest_blocklist():
            print("Restored latest blocklist.")
        else:
            print("No blocklist archive found.")
