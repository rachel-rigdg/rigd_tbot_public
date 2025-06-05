# tbot_bot/core/scripts/init_system_users.py
# Initializes SYSTEM_USERS.db from system_users_schema.sql using path_resolver

import sys
from pathlib import Path
import sqlite3
from tbot_bot.support.path_resolver import get_schema_path
from tbot_bot.support.utils_log import log_event

SCHEMA_FILE = "system_users_schema.sql"
DB_FILE = "SYSTEM_USERS.db"

def init_system_users():
    """
    Initializes SYSTEM_USERS.db with schema (idempotent). Does not add any user.
    """
    print("[init_system_users] Starting initialization...", file=sys.stderr)
    db_path = Path(__file__).resolve().parents[1] / "databases" / DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = get_schema_path(SCHEMA_FILE)
    print(f"[init_system_users] Resolved schema path: {schema_path}", file=sys.stderr)
    if not Path(schema_path).is_file():
        log_event("init_system_users", f"Schema missing: {schema_path}", level="error")
        print(f"[init_system_users] ERROR: Schema missing: {schema_path}", file=sys.stderr)
        return

    try:
        with sqlite3.connect(str(db_path)) as conn, open(schema_path, "r", encoding="utf-8") as f:
            sql_script = f.read()
            print(f"[init_system_users] Creating DB at: {db_path}", file=sys.stderr)
            conn.executescript(sql_script)
            log_event("init_system_users", f"SYSTEM_USERS.db schema initialized at {db_path}")
            print(f"[init_system_users] ✓ SYSTEM_USERS.db schema initialized at {db_path}", file=sys.stderr)
    except Exception as e:
        log_event("init_system_users", f"Failed schema exec: {e}", level="error")
        print(f"[init_system_users] ✗ Schema exec failed: {e}", file=sys.stderr)

def main():
    init_system_users()

if __name__ == "__main__":
    main()
