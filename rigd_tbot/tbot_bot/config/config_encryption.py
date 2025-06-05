# tbot_bot/config/config_encryption.py
# v038-compliant: All file paths are resolved via path_resolver, all key loads and writes are spec-conformant

import json
import shutil
import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from tbot_bot.support.path_resolver import get_secret_path
from tbot_bot.support.utils_log import log_event

KEY_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"
BACKUP_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def load_key(category: str) -> bytes:
    print(f"[load_key] Loading key for: {category}")
    key_path = KEY_DIR / f"{category}.key"
    if not key_path.is_file():
        raise FileNotFoundError(f"[config_encryption] Missing key file: {key_path}")
    key_text = key_path.read_text(encoding="utf-8").strip()
    if len(key_text) != 44:  # Fernet base64 key length
        raise ValueError(f"[config_encryption] Invalid Fernet key length for {category}")
    return key_text.encode()

def backup_file(path: Path) -> None:
    if not path.is_file():
        return
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_name = f".{path.name}.{timestamp}.bak"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(str(path), str(backup_path))
    log_event("config_encryption", f"Backup created: {backup_path}")
    print(f"[backup_file] Created backup: {backup_path}")

def encrypt_and_write(category: str, data: dict) -> None:
    print(f"[encrypt_and_write] Encrypting: {category}")
    key = load_key(category)
    fernet = Fernet(key)
    raw_json = json.dumps(data, indent=2).encode("utf-8")
    enc_file = Path(get_secret_path(category))
    backup_file(enc_file)
    encrypted = fernet.encrypt(raw_json)
    with open(enc_file, "wb") as f:
        f.write(encrypted)
    log_event("config_encryption", f"Encrypted config for category '{category}' to {enc_file}")
    print(f"[encrypt_and_write] Completed for: {category}")

def encrypt_env_bot_from_bytes(raw_bytes: bytes) -> None:
    print("[encrypt_env_bot_from_bytes] Encrypting .env_bot")
    category = "env_bot"
    key = load_key(category)
    fernet = Fernet(key)
    enc_file = Path(get_secret_path("env_bot"))
    backup_file(enc_file)
    encrypted = fernet.encrypt(raw_bytes)
    with open(enc_file, "wb") as f:
        f.write(encrypted)
    log_event("config_encryption", f"Encrypted raw .env_bot bytes → {enc_file}")
    print("[encrypt_env_bot_from_bytes] Completed")

def secure_write_encrypted_category(category: str, data_dict: dict, path_override: str = None) -> None:
    print(f"[secure_write_encrypted_category] Encrypting: {category}")
    # Always use get_secret_path for encrypted config file targets, unless path_override is given
    if path_override:
        enc_file = Path(path_override)
        print(f"[secure_write_encrypted_category] Using override path for: {category} -> {enc_file}")
    else:
        enc_file = Path(get_secret_path(category))
        print(f"[secure_write_encrypted_category] Using secret path for: {category} -> {enc_file}")
    key = load_key(category)
    fernet = Fernet(key)
    if category in ("bot_identity", "network_config"):
        # Write as JSON for these core identity categories (bootstrap-compliant)
        content = json.dumps(data_dict, indent=2).encode("utf-8")
    else:
        # Write as simple key=value lines for all other categories
        lines = [f"{k}={v}" for k, v in data_dict.items() if v is not None]
        content = "\n".join(lines).encode("utf-8")
    backup_file(enc_file)
    enc_file.write_bytes(fernet.encrypt(content))
    log_event("config_encryption", f"Encrypted config for category '{category}' to {enc_file}")
    print(f"[secure_write_encrypted_category] Completed for: {category}")
