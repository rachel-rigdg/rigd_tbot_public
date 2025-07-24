# tbot_bot/runtime/ledger_snapshot.py
# One-shot End-of-Day ledger snapshot/export module.
# Dumps the full ledger_entries table (and optionally trades) to a timestamped CSV and SQLite backup for compliance and rollback.
# Intended to be scheduled and launched by tbot_supervisor.py after market close.

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import shutil
import sqlite3
import csv

# Add project root for imports
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.decrypt_secrets import load_bot_identity

def get_db_path():
    # Locate the main ledger SQLite DB (assumes path per your system)
    config = get_bot_config()
    db_path = config.get("LEDGER_DB_PATH")
    if db_path and os.path.exists(db_path):
        return db_path
    # fallback
    possible = ROOT_DIR / "tbot_bot" / "data" / "ledger.db"
    if possible.exists():
        return str(possible)
    raise FileNotFoundError("Could not locate ledger database file.")

def get_snapshot_dir(bot_id):
    # Store under tbot_bot/output/{bot_identity}/ledgers/ledger_snapshots/
    d = ROOT_DIR / "tbot_bot" / "output" / bot_id / "ledgers" / "ledger_snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d

def main():
    # Determine snapshot time and bot/entity code
    snapshot_time = datetime.now(timezone.utc)
    ts = snapshot_time.strftime("%Y-%m-%dT%H%M%SZ")
    try:
        bot_id = load_bot_identity()
    except Exception:
        bot_id = "unknown"
    entity_code = bot_id.split("_")[0] if bot_id and "_" in bot_id else "unknown"

    db_path = get_db_path()
    snapshot_dir = get_snapshot_dir(bot_id)

    # --- 1. SQLite backup ---
    sqlite_backup_path = snapshot_dir / f"ledger_{entity_code}_{ts}.sqlite3"
    shutil.copy2(db_path, sqlite_backup_path)
    print(f"[ledger_snapshot] SQLite ledger DB backed up to: {sqlite_backup_path}")

    # --- 2. CSV export (full table) ---
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    ledger_csv_path = snapshot_dir / f"ledger_entries_{entity_code}_{ts}.csv"
    with open(ledger_csv_path, "w", newline='', encoding="utf-8") as csvfile:
        writer = None
        cursor.execute("SELECT * FROM ledger_entries")
        columns = [desc[0] for desc in cursor.description]
        writer = csv.DictWriter(csvfile, fieldnames=columns)
        writer.writeheader()
        for row in cursor.fetchall():
            writer.writerow(dict(zip(columns, row)))
    print(f"[ledger_snapshot] ledger_entries table exported to: {ledger_csv_path}")

    # Optional: also export trades table if present
    try:
        cursor.execute("SELECT * FROM trades")
        trades_csv_path = snapshot_dir / f"trades_{entity_code}_{ts}.csv"
        with open(trades_csv_path, "w", newline='', encoding="utf-8") as csvfile:
            columns = [desc[0] for desc in cursor.description]
            writer = csv.DictWriter(csvfile, fieldnames=columns)
            writer.writeheader()
            for row in cursor.fetchall():
                writer.writerow(dict(zip(columns, row)))
        print(f"[ledger_snapshot] trades table exported to: {trades_csv_path}")
    except Exception as e:
        print(f"[ledger_snapshot] No trades table or export error: {e}")

    conn.close()
    print("[ledger_snapshot] Snapshot completed successfully.")

if __name__ == "__main__":
    main()
