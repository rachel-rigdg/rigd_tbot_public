# tbot_bot/core/scripts/init_system.py
# Initializes SYSTEM.db from system_schema.sql using path_resolver

import sys
import sqlite3
from pathlib import Path
from tbot_bot.support.path_resolver import get_schema_path
from tbot_bot.support.utils_log import log_event

SCHEMA_FILE = "system_schema.sql"
DB_FILE = "SYSTEM.db"

def init_system():
    """
    Initializes SYSTEM.db using the SQL schema.
    """
    print("[init_system] Starting initialization...", file=sys.stderr)
    db_path = Path(__file__).resolve().parents[1] / "databases" / DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = get_schema_path(SCHEMA_FILE)
    print(f"[init_system] Resolved schema path: {schema_path}", file=sys.stderr)
    if not Path(schema_path).is_file():
        log_event("init_system", f"Schema missing: {schema_path}", level="error")
        print(f"[init_system] ERROR: Schema missing: {schema_path}", file=sys.stderr)
        return

    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            print(f"[init_system] Creating DB at: {db_path}", file=sys.stderr)
            conn.executescript(schema_sql)
            log_event("init_system", f"SYSTEM.db initialized at {db_path}")
            print(f"[init_system] ✓ SYSTEM.db initialized at {db_path}", file=sys.stderr)
    except Exception as e:
        log_event("init_system", f"Error initializing {db_path}: {e}", level="error")
        print(f"[init_system] ✗ Error initializing {db_path}: {e}", file=sys.stderr)

def main():
    init_system()

if __name__ == "__main__":
    main()
