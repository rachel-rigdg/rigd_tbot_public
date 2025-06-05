# tools/hash_password.py
# Creates bcrypt-hashed login credentials, saves Fernet key, and inserts user into SYSTEM_USERS.db

import sys
import bcrypt
import sqlite3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import os

# === Flags ===
NO_PROMPT = "--no-prompt" in sys.argv

# === Setup paths per RIGD spec ===
BASE_DIR = Path(__file__).resolve().parents[1]
KEY_DIR = BASE_DIR / "tbot_bot" / "storage" / "keys"
BACKUP_DIR = BASE_DIR / "tbot_bot" / "storage" / "backups"
DB_PATH = BASE_DIR / "tbot_bot" / "core" / "databases" / "SYSTEM_USERS.db"
SUPPORT_ENV_PATH = BASE_DIR / "tbot_bot" / "support" / ".env"

LOGIN_KEY_FILE = KEY_DIR / "login.key"
LOGIN_BACKUP = BACKUP_DIR / f"login_{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.key"
CREDS_OUTPUT = BACKUP_DIR / f"hashed_credentials_{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"

KEY_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# === Load .env for env-var driven input (optional) ===
load_dotenv(dotenv_path=SUPPORT_ENV_PATH)

# === Generate or load Fernet key for login encryption ===
if not LOGIN_KEY_FILE.exists() or LOGIN_KEY_FILE.stat().st_size == 0:
    fernet_key = Fernet.generate_key()
    LOGIN_KEY_FILE.write_bytes(fernet_key)
    print(f"Created new Fernet login key at: {LOGIN_KEY_FILE}")
else:
    fernet_key = LOGIN_KEY_FILE.read_bytes()
    print(f"Loaded existing Fernet login key from: {LOGIN_KEY_FILE}")

# === Prompt or pull input ===
if NO_PROMPT:
    username = os.getenv("ENCRYPT_PLAIN_USERNAME", "").strip()
    password = os.getenv("ENCRYPT_PLAIN_PASSWORD", "").strip()
    email = os.getenv("ENCRYPT_PLAIN_EMAIL", "").strip()
    if not email:
        print("Missing email environment variable ENCRYPT_PLAIN_EMAIL. Aborting.")
        sys.exit(1)
else:
    username = input("Enter new username: ").strip()
    password = input("Enter new password: ").strip()
    email = input("Enter email address: ").strip()

if not username or not password or not email:
    print("Missing username, password, or email. Aborting.")
    sys.exit(1)

# === Hash password with bcrypt ===
salt = bcrypt.gensalt()
hashed_password = bcrypt.hashpw(password.encode(), salt)

# === Backup bcrypt hashed password only ===
LOGIN_BACKUP.write_bytes(hashed_password)
print(f"Hashed password backup saved to: {LOGIN_BACKUP}")

# === Optional output: store structured JSON for manual inspection or accounting preload ===
CREDS_OUTPUT.write_text(
    f'{{\n  "username": "{username}",\n  "email": "{email}",\n  "hashed_password": "{hashed_password.decode()}"\n}}\n',
    encoding="utf-8"
)
print(f"Hashed credentials JSON exported to: {CREDS_OUTPUT}")

# === Insert user into SYSTEM_USERS.db ===
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username FROM system_users WHERE username = ?",
        (username,)
    )
    if cursor.fetchone():
        print(f"User '{username}' already exists in SYSTEM_USERS.db — skipping insert.")
    else:
        cursor.execute(
            "INSERT INTO system_users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, email, hashed_password.decode(), "admin")
        )
        conn.commit()
        print(f"User '{username}' inserted into SYSTEM_USERS.db successfully.")
except Exception as e:
    print(f"Failed to insert user into SYSTEM_USERS.db: {e}")
finally:
    if conn:
        conn.close()

print("\nUser credential hashing and DB insertion complete.")
