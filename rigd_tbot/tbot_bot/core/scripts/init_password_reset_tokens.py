# tbot_bot/core/scripts/init_password_reset_tokens.py
# Initializes PASSWORD_RESET_TOKENS.db from password_reset_schema.sql using path_resolver

import sys
from pathlib import Path
import sqlite3
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tbot_bot.support.path_resolver import get_schema_path
from tbot_bot.support.utils_log import log_event

SCHEMA_FILE = "password_reset_schema.sql"
DB_FILE = "PASSWORD_RESET_TOKENS.db"

def init_password_reset_tokens():
    """
    Initializes PASSWORD_RESET_TOKENS.db using the SQL schema.
    Safely skips duplicate index errors.
    """
    print("[init_password_reset_tokens] Starting initialization...", file=sys.stderr)
    try:
        schema_path = get_schema_path(SCHEMA_FILE)
        print(f"[init_password_reset_tokens] Resolved schema path: {schema_path}", file=sys.stderr)
        if not Path(schema_path).is_file():
            raise FileNotFoundError(f"Schema file does not exist: {schema_path}")
    except Exception as e:
        log_event("init_password_reset_tokens", f"✗ Schema file not found: {e}", level="error")
        print(f"[init_password_reset_tokens] ✗ Schema file not found: {e}", file=sys.stderr)
        return

    db_path = Path(__file__).resolve().parents[1] / "databases" / DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[init_password_reset_tokens] Database target path: {db_path}", file=sys.stderr)

    conn = None
    try:
        print(f"[init_password_reset_tokens] Creating or updating DB at: {db_path}", file=sys.stderr)
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = sqlite3.connect(str(db_path))
        print(f"[init_password_reset_tokens] Connected to DB: {db_path}", file=sys.stderr)
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
        existing_indexes = set(row[0] for row in cursor.fetchall())

        statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
        for stmt in statements:
            if stmt.upper().startswith("CREATE INDEX"):
                index_name = stmt.split()[2]
                if index_name in existing_indexes:
                    print(f"[init_password_reset_tokens] Skipping existing index: {index_name}", file=sys.stderr)
                    continue
            try:
                cursor.execute(stmt)
            except sqlite3.Error as e:
                if "already exists" in str(e).lower():
                    print(f"[init_password_reset_tokens] Ignored error (likely exists): {e}", file=sys.stderr)
                    continue
                else:
                    raise

        conn.commit()
        log_event("init_password_reset_tokens", f"✓ PASSWORD_RESET_TOKENS.db initialized: {db_path}")
        print(f"[init_password_reset_tokens] ✓ PASSWORD_RESET_TOKENS.db initialized: {db_path}", file=sys.stderr)
    except sqlite3.Error as e:
        log_event("init_password_reset_tokens", f"✗ Database init error: {e}", level="error")
        print(f"[init_password_reset_tokens] ✗ Database init error: {e}", file=sys.stderr)
    finally:
        if conn:
            conn.close()
            print(f"[init_password_reset_tokens] Connection closed: {db_path}", file=sys.stderr)

def main():
    init_password_reset_tokens()

if __name__ == "__main__":
    main()
