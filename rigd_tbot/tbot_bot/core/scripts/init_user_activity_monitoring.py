# tbot_bot/core/scripts/init_user_activity_monitoring.py
# Initializes USER_ACTIVITY_MONITORING.db from user_activity_monitoring_schema.sql using path_resolver

import sys
from pathlib import Path
import sqlite3
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tbot_bot.support.path_resolver import get_schema_path
from tbot_bot.support.utils_log import log_event

SCHEMA_FILE = "user_activity_monitoring_schema.sql"
DB_FILE = "USER_ACTIVITY_MONITORING.db"

def init_user_activity_monitoring():
    print("[init_user_activity_monitoring] Starting initialization...", file=sys.stderr)
    db_path = Path(__file__).resolve().parents[1] / "databases" / DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = get_schema_path(SCHEMA_FILE)
    print(f"[init_user_activity_monitoring] Resolved schema path: {schema_path}", file=sys.stderr)
    if not Path(schema_path).is_file():
        log_event("init_user_activity_monitoring", f"Schema missing: {schema_path}", level="error")
        print(f"[init_user_activity_monitoring] ERROR: Schema missing: {schema_path}", file=sys.stderr)
        return

    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
            existing_indexes = set(row[0] for row in cursor.fetchall())
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
            for stmt in statements:
                if stmt.upper().startswith("CREATE INDEX"):
                    index_name = stmt.split()[2]
                    if index_name in existing_indexes:
                        print(f"[init_user_activity_monitoring] Skipping existing index: {index_name}", file=sys.stderr)
                        continue
                try:
                    cursor.execute(stmt)
                except sqlite3.Error as e:
                    if "already exists" in str(e).lower():
                        print(f"[init_user_activity_monitoring] Ignored error (likely exists): {e}", file=sys.stderr)
                        continue
                    else:
                        raise
            conn.commit()
            log_event("init_user_activity_monitoring", f"USER_ACTIVITY_MONITORING.db initialized at {db_path}")
            print(f"[init_user_activity_monitoring] ✓ USER_ACTIVITY_MONITORING.db initialized at {db_path}", file=sys.stderr)
    except Exception as e:
        log_event("init_user_activity_monitoring", f"Error initializing {db_path}: {e}", level="error")
        print(f"[init_user_activity_monitoring] ✗ Error initializing {db_path}: {e}", file=sys.stderr)

def main():
    init_user_activity_monitoring()

if __name__ == "__main__":
    main()
