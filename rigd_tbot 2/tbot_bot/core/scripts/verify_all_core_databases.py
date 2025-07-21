# tbot_bot/core/scripts/verify_all_core_databases.py
# Verifies initialization of all tbot core databases by checking for expected tables

import sqlite3
from pathlib import Path
from tbot_bot.support.utils_log import log_event

CORE_DB_FOLDER = Path(__file__).resolve().parent.parent / "databases"

CORE_DATABASES = [
    "LEDGER_STATUS.db",
    "PASSWORD_RESET_TOKENS.db",
    "SYSTEM_LOGS.db",
    "SYSTEM.db",
    "SYSTEM_USERS.db",
    "USER_ACTIVITY_MONITORING.db",
]

def verify_databases():
    for db_file in CORE_DATABASES:
        db_path = CORE_DB_FOLDER / db_file
        print(f"\nVerifying database: {db_file}")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            if tables:
                print("  Tables found:")
                for table in tables:
                    print(f"    - {table[0]}")
                log_event("verify_all_core_databases", f"{db_file} contains {len(tables)} tables: {[t[0] for t in tables]}")
            else:
                print("  ⚠ No tables found in this database.")
                log_event("verify_all_core_databases", f"{db_file} contains NO tables!", level="error")
            conn.close()
        except Exception as e:
            print(f"  ❌ Error connecting to {db_file}: {e}")
            log_event("verify_all_core_databases", f"Error connecting to {db_file}: {e}", level="error")

if __name__ == "__main__":
    verify_databases()
