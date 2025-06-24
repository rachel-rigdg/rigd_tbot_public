# tbot_web/py/auth_web.py
# Handles web user authentication and password validation

import os
import sqlite3
import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from functools import wraps
from flask import session, abort, g
from pathlib import Path
from tbot_bot.support.utils_log import log_event

# Path to key and database (no loading at import time)
KEY_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "login.key"
DB_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "core" / "databases" / "SYSTEM_USERS.db"

def get_encryption_key() -> bytes:
    """
    Loads the Fernet encryption key for login.
    Raises FileNotFoundError if key missing or invalid.
    """
    if not KEY_PATH.exists():
        raise FileNotFoundError(f"[auth_web] Missing login.key at: {KEY_PATH}")
    key = KEY_PATH.read_text().strip()
    # Validate key length and base64 format
    if len(key) != 44:
        raise ValueError("[auth_web] Invalid Fernet key length in login.key")
    return key.encode()

def decrypt_password(encrypted_password: str) -> str:
    """
    Decrypts a Fernet-encrypted password string.
    Used to validate login credentials stored in SYSTEM_USERS.db.
    """
    try:
        fernet = Fernet(get_encryption_key())
        decrypted = fernet.decrypt(encrypted_password.encode())
        return decrypted.decode()
    except InvalidToken:
        log_event("auth_web", "Failed to decrypt stored password: InvalidToken", level="error")
        raise
    except Exception as e:
        log_event("auth_web", f"Unexpected error decrypting password: {e}", level="error")
        raise

def get_db_connection():
    """
    Returns a SQLite connection to SYSTEM_USERS.db with foreign keys enabled.
    Raises FileNotFoundError if DB missing.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"[auth_web] SYSTEM_USERS.db not found at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def upsert_user(username: str, password: str, email: str = None, role: str = "viewer") -> None:
    """
    Inserts or updates a user record in SYSTEM_USERS.db.
    Password is securely hashed and encrypted using Fernet.
    Role is required; first user should be 'admin'.
    Raises ValueError if username/password missing.
    """
    if not username or not password:
        raise ValueError("Username and password are required")

    # Hash the password with bcrypt
    hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    # Encrypt the bcrypt hash for storage
    fernet = Fernet(get_encryption_key())
    encrypted_pw = fernet.encrypt(hashed_pw).decode()

    email = email or ""
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO system_users (username, password_hash, email, role, account_status)
            VALUES (?, ?, ?, ?, 'active')
            ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, email = excluded.email, role = excluded.role;
            """,
            (username, encrypted_pw, email, role)
        )
        conn.commit()
        log_event("auth_web", f"User {username} created or updated with role {role}.")
    except Exception as e:
        log_event("auth_web", f"Failed to upsert user {username}: {e}", level="error")
        raise
    finally:
        conn.close()

def get_user_role(username: str) -> str:
    """
    Fetches the user's role from SYSTEM_USERS.db.
    Returns 'viewer' if not found or on error.
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT role FROM system_users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
        return "viewer"
    except Exception as e:
        log_event("auth_web", f"Failed to fetch role for user {username}: {e}", level="error")
        return "viewer"
    finally:
        conn.close()

def validate_user(username: str, password: str) -> bool:
    """
    Validates a username/password combo against the SYSTEM_USERS.db hash.
    Returns True if valid, False otherwise.
    """
    if not username or not password:
        return False

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT password_hash FROM system_users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        if row is None:
            return False

        encrypted_hash = row[0]
        if isinstance(encrypted_hash, bytes):
            encrypted_hash = encrypted_hash.decode()
        fernet = Fernet(get_encryption_key())
        try:
            stored_hash = fernet.decrypt(encrypted_hash.encode())
        except InvalidToken:
            log_event("auth_web", f"Invalid encryption token for user {username}", level="error")
            return False

        return bcrypt.checkpw(password.encode("utf-8"), stored_hash)
    except Exception as e:
        log_event("auth_web", f"Exception during user validation for {username}: {e}", level="error")
        return False
    finally:
        conn.close()

def user_exists() -> bool:
    """
    Returns True if there is at least one active user in SYSTEM_USERS.db.
    """
    try:
        conn = get_db_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM system_users WHERE account_status = 'active';")
        count = cursor.fetchone()[0]
        return count > 0
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass

def rbac_required(role: str = None):
    """
    Role-Based Access Control decorator for Flask endpoints.
    If `role` is specified, requires user to have that role.
    Defaults to requiring any authenticated user.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user' not in session:
                abort(401)
            if role:
                user_role = session.get("role", None)
                if user_role != role:
                    abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator

def get_current_user():
    """
    Returns current logged-in user from session, or None.
    Used for operational UI and admin/role checks.
    """
    return session.get("user", None)
