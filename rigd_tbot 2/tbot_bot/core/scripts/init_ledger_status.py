# tbot_bot/core/scripts/init_ledger_status.py
# Initializes LEDGER_STATUS.db from ledger_status_schema.sql using path_resolver

import sys
import sqlite3
from pathlib import Path
from tbot_bot.support.path_resolver import get_schema_path
from tbot_bot.support.utils_log import log_event

SCHEMA_FILE = "ledger_status_schema.sql"
DB_FILE = "LEDGER_STATUS.db"

def init_ledger_status():
    """
    Initializes the LEDGER_STATUS.db database using the schema file.
    """
    print("[init_ledger_status] Starting initialization...", file=sys.stderr)
    conn = None
    try:
        schema_path = get_schema_path(SCHEMA_FILE)
        print(f"[init_ledger_status] Resolved schema path: {schema_path}", file=sys.stderr)
        if not Path(schema_path).is_file():
            raise FileNotFoundError(f"Schema file does not exist: {schema_path}")
    except Exception as e:
        log_event("init_ledger_status", f"✗ Schema not found: {e}", level="error")
        print(f"[init_ledger_status] ✗ Schema not found: {e}", file=sys.stderr)
        return

    db_path = Path(__file__).resolve().parents[1] / "databases" / DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[init_ledger_status] Database target path: {db_path}", file=sys.stderr)

    try:
        print(f"[init_ledger_status] Creating DB at: {db_path}", file=sys.stderr)
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = sqlite3.connect(str(db_path))
        print(f"[init_ledger_status] Connected to DB: {db_path}", file=sys.stderr)
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        cursor.executescript(schema_sql)
        conn.commit()
        log_event("init_ledger_status", f"✓ LEDGER_STATUS.db initialized: {db_path}")
        print(f"[init_ledger_status] ✓ LEDGER_STATUS.db initialized: {db_path}", file=sys.stderr)
    except Exception as e:
        log_event("init_ledger_status", f"✗ Error initializing {db_path}: {e}", level="error")
        print(f"[init_ledger_status] ✗ Error initializing {db_path}: {e}", file=sys.stderr)
    finally:
        if conn:
            conn.close()
            print(f"[init_ledger_status] Connection closed: {db_path}", file=sys.stderr)

def main():
    init_ledger_status()

if __name__ == "__main__":
    main()
