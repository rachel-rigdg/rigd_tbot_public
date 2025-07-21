# tbot_bot/support/holdings_secrets.py
# Module for encrypted holdings config/secrets CRUD and atomic/rollback support. 100% audit-traceable.

import os
import json
import shutil
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken
from tbot_bot.support.path_resolver import (
    resolve_holdings_secrets_path,
    resolve_holdings_secrets_backup_dir,
    resolve_holdings_secrets_key_path,
)
from tbot_bot.support.utils_log import log_event

HOLDINGS_SECRETS_FILE = resolve_holdings_secrets_path()
HOLDINGS_SECRETS_KEY_FILE = resolve_holdings_secrets_key_path()
BACKUP_DIR = resolve_holdings_secrets_backup_dir()
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def _get_fernet():
    """Load Fernet key for encryption/decryption."""
    with open(HOLDINGS_SECRETS_KEY_FILE, "rb") as kf:
        key = kf.read().strip()
    return Fernet(key)

def load_holdings_secrets():
    """
    Loads and decrypts the holdings_secrets.json.enc file.
    Returns {} if not present.
    Raises on invalid key.
    """
    if not HOLDINGS_SECRETS_FILE.exists():
        return {}
    with open(HOLDINGS_SECRETS_FILE, "rb") as f:
        data = f.read()
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(data)
        return json.loads(decrypted.decode("utf-8"))
    except InvalidToken:
        raise RuntimeError("Invalid holdings secrets key or file is corrupted.")

def save_holdings_secrets(data: dict, user: str = "system", reason: str = "update"):
    """
    Atomically saves an updated (encrypted) holdings config file, rotating backups and audit-logging all state changes.
    Args:
        data: dict, secrets/config to save
        user: str, operator or system
        reason: str, audit/compliance reason
    """
    if HOLDINGS_SECRETS_FILE.exists():
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        backup_path = BACKUP_DIR / f"holdings_secrets_{timestamp}.json.enc"
        shutil.copy2(HOLDINGS_SECRETS_FILE, backup_path)
    fernet = _get_fernet()
    enc = fernet.encrypt(json.dumps(data, indent=2).encode("utf-8"))
    tmp_path = HOLDINGS_SECRETS_FILE.with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        f.write(enc)
    os.replace(tmp_path, HOLDINGS_SECRETS_FILE)
    # Audit log
    log_event(
        action="holdings_secrets_save",
        user=user or "system",
        details={"reason": reason, "file": str(HOLDINGS_SECRETS_FILE)},
        timestamp=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    )

def rotate_holdings_key(new_key: bytes, user: str):
    """
    Rotates the holdings encryption key, backing up all previous state and re-encrypting the config.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    key_backup = BACKUP_DIR / f"holdings_key_{timestamp}.key"
    shutil.copy2(HOLDINGS_SECRETS_KEY_FILE, key_backup)
    secrets_data = load_holdings_secrets()
    with open(HOLDINGS_SECRETS_KEY_FILE, "wb") as kf:
        kf.write(new_key)
    save_holdings_secrets(secrets_data, user, reason="key_rotation")
    log_event(
        action="holdings_key_rotation",
        user=user,
        details={"file": str(HOLDINGS_SECRETS_KEY_FILE)},
        timestamp=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    )

def update_holdings_secrets(patch: dict, user: str = "system", reason: str = "update"):
    """
    Updates holdings secrets atomically with a dict patch, audit-logging all changes.
    """
    secrets = load_holdings_secrets()
    secrets.update(patch)
    save_holdings_secrets(secrets, user, reason)

def get_holdings_history():
    """
    Returns a sorted list of all backup files for holdings_secrets (for restore/audit purposes).
    """
    return sorted(
        [f for f in BACKUP_DIR.glob("holdings_secrets_*.json.enc")],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

def restore_holdings_secrets(backup_file: str, user: str = "system"):
    """
    [STUB/OPTIONAL] Restores holdings secrets from a given backup file (audit-logs the restore).
    Not auto-invoked; for manual/operator-driven rollbacks only.
    """
    backup_path = BACKUP_DIR / backup_file
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")
    shutil.copy2(backup_path, HOLDINGS_SECRETS_FILE)
    log_event(
        action="holdings_secrets_restore",
        user=user,
        details={"file": str(HOLDINGS_SECRETS_FILE), "restored_from": str(backup_path)},
        timestamp=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    )
