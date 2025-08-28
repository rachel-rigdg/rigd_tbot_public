# tbot_bot/runtime/ledger_snapshot.py
# One-shot End-of-Day ledger snapshot/export module.
# Dumps the full trades table (OFX-compliant) to a timestamped CSV and SQLite backup for compliance and rollback.
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

from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_snapshot_dir
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.utils_log import log_event  # <- added

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def main():
    # Determine snapshot time and bot/entity code
    snapshot_time = datetime.now(timezone.utc)
    ts = snapshot_time.strftime("%Y-%m-%dT%H%M%SZ")
    try:
        entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    except Exception:
        entity_code = jurisdiction_code = broker_code = bot_id = "unknown"

    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    snapshot_dir = resolve_ledger_snapshot_dir(entity_code, jurisdiction_code, broker_code, bot_id)
    os.makedirs(snapshot_dir, exist_ok=True)

    # --- 1. SQLite backup ---
    sqlite_backup_path = Path(snapshot_dir) / f"ledger_{entity_code}_{ts}.sqlite3"
    shutil.copy2(db_path, sqlite_backup_path)
    print(f"[ledger_snapshot] SQLite ledger DB backed up to: {sqlite_backup_path}")

    # --- 2. CSV export (trades table) ---
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    trades_csv_path = Path(snapshot_dir) / f"trades_{entity_code}_{ts}.csv"
    try:
        cursor.execute("SELECT * FROM trades")
        columns = [desc[0] for desc in cursor.description]
        with open(trades_csv_path, "w", newline='', encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns)
            writer.writeheader()
            for row in cursor.fetchall():
                writer.writerow(dict(zip(columns, row)))
        print(f"[ledger_snapshot] trades table exported to: {trades_csv_path}")
    except Exception as e:
        print(f"[ledger_snapshot] trades table export error: {e}")

    conn.close()
    # concise completion log
    end_ts = datetime.now(timezone.utc).isoformat()
    log_event("ledger_snapshot", f"snapshot completed @ {end_ts}")  # <- added
    print("[ledger_snapshot] Snapshot completed successfully.")

if __name__ == "__main__":
    main()
