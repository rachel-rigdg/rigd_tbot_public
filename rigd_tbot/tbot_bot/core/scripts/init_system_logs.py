# tbot_bot/core/scripts/init_system_logs.py
# Initializes SYSTEM_LOGS.db from system_logs_schema.sql using path_resolver

import sys
from pathlib import Path
import sqlite3
from tbot_bot.support.path_resolver import get_schema_path
from tbot_bot.support.utils_log import log_event

SCHEMA_FILE = "system_logs_schema.sql"
DB_FILE = "SYSTEM_LOGS.db"

def init_system_logs():
    """
    Creates or updates SYSTEM_LOGS.db using the schema.
    Skips creation of indexes or tables if they already exist to avoid errors.
    """
    print("[init_system_logs] Starting initialization...", file=sys.stderr)
    conn = None
    try:
        schema_path = get_schema_path(SCHEMA_FILE)
        print(f"[init_system_logs] Resolved schema path: {schema_path}", file=sys.stderr)
        if not Path(schema_path).is_file():
            raise FileNotFoundError(f"Schema file does not exist: {schema_path}")
    except Exception as e:
        log_event("init_system_logs", f"✗ Schema file not found: {e}", level="error")
        print(f"[init_system_logs] ✗ Schema file not found: {e}", file=sys.stderr)
        return

    db_path = Path(__file__).resolve().parents[1] / "databases" / DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[init_system_logs] Database target directory: {db_path.parent}", file=sys.stderr)

    try:
        print(f"[init_system_logs] Creating or updating DB at: {db_path}", file=sys.stderr)
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = sqlite3.connect(str(db_path))
        print(f"[init_system_logs] Connected to DB: {db_path}", file=sys.stderr)
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
        existing_indexes = set(row[0] for row in cursor.fetchall())

        statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
        for stmt in statements:
            if stmt.upper().startswith("CREATE INDEX"):
                index_name = stmt.split()[2]
                if index_name in existing_indexes:
                    print(f"[init_system_logs] Skipping existing index: {index_name}", file=sys.stderr)
                    continue
            try:
                cursor.execute(stmt)
            except sqlite3.Error as e:
                if "already exists" in str(e).lower():
                    print(f"[init_system_logs] Ignored error (likely exists): {e}", file=sys.stderr)
                    continue
                else:
                    raise

        conn.commit()
        log_event("init_system_logs", f"✓ SYSTEM_LOGS.db initialized at: {db_path}")
        print(f"[init_system_logs] ✓ SYSTEM_LOGS.db initialized at: {db_path}", file=sys.stderr)
    except sqlite3.Error as e:
        log_event("init_system_logs", f"✗ Database init error: {e}", level="error")
        print(f"[init_system_logs] ✗ Database init error: {e}", file=sys.stderr)
    finally:
        if conn:
            conn.close()
            print(f"[init_system_logs] Connection closed: {db_path}", file=sys.stderr)

def main():
    init_system_logs()

if __name__ == "__main__":
    main()
