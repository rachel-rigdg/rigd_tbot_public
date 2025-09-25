# tbot_bot/config/security_bot.py
# Encrypts/decrypts .env_bot to .env_bot.enc using ONLY env_bot.key (never env.key).
# Supports atomic Fernet key rotation, robust backup, and best practice hardening.

from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
from tbot_bot.support.utils_log import log_event

# === STRICT PATH ENFORCEMENT: env_bot only ===
BOT_ENV_PATH = Path(__file__).resolve().parent.parent / "support" / ".env_bot"
ENC_BOT_ENV_PATH = Path(__file__).resolve().parent.parent / "support" / ".env_bot.enc"
KEY_PATH = Path(__file__).resolve().parent.parent / "storage" / "keys" / "env_bot.key"
BACKUP_DIR = Path(__file__).resolve().parent.parent / "storage" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def _backup_file(src_path: Path, suffix: str):
    """
    Copies the source file to backups with a timestamp and suffix.
    """
    if src_path.exists():
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_path = BACKUP_DIR / f"{src_path.name}.{suffix}_{timestamp}.bak"
        backup_path.write_bytes(src_path.read_bytes())
        log_event("security_bot", f"Backup created: {backup_path}")
        print(f"[security_bot] Backup created: {backup_path}", file=sys.stderr)

def load_encryption_key() -> bytes:
    """
    Loads the Fernet encryption key from storage/keys/env_bot.key (NEVER env.key).
    """
    if not KEY_PATH.exists():
        raise FileNotFoundError(f"Missing encryption key: {KEY_PATH}")
    print(f"[security_bot] Loading encryption key from: {KEY_PATH}", file=sys.stderr)
    return KEY_PATH.read_text(encoding="utf-8").strip().encode()

def encrypt_env_bot(rotate_key=False):
    """
    Encrypts the .env_bot file into .env_bot.enc using Fernet key.
    If rotate_key=True, generates a new key and backs up old key+enc before overwriting.
    """
    if not BOT_ENV_PATH.exists():
        raise FileNotFoundError(f"{BOT_ENV_PATH} not found")

    raw_data = BOT_ENV_PATH.read_bytes()
    encrypt_env_bot_from_bytes(raw_data, rotate_key=rotate_key)

def encrypt_env_bot_from_bytes(raw_bytes: bytes, rotate_key=False):
    """
    Encrypts raw bytes into .env_bot.enc using Fernet key.
    If rotate_key=True, generates a new key and backs up old key+enc before overwriting.
    """
    if rotate_key:
        _backup_file(KEY_PATH, "env_bot_key")
        _backup_file(ENC_BOT_ENV_PATH, "env_bot_enc")
        new_key = Fernet.generate_key()
        KEY_PATH.write_text(new_key.decode("utf-8") + "\n")
        log_event("security_bot", f"Rotated env_bot.key: {KEY_PATH}")
        print(f"[security_bot] Rotated env_bot.key: {KEY_PATH}", file=sys.stderr)
        key = new_key
    else:
        key = load_encryption_key()

    fernet = Fernet(key)
    encrypted_data = fernet.encrypt(raw_bytes)
    ENC_BOT_ENV_PATH.write_bytes(encrypted_data)
    log_event("security_bot", "Encrypted .env_bot to .env_bot.enc" + (" [rotated key]" if rotate_key else ""))
    print(f"[security_bot] Encrypted .env_bot to .env_bot.enc{' [rotated key]' if rotate_key else ''}", file=sys.stderr)

    # Post-encrypt: verify round-trip decryption (robustness)
    try:
        decrypted_data = fernet.decrypt(encrypted_data)
        if decrypted_data != raw_bytes:
            raise ValueError("Verification mismatch: decrypted output does not match input")
        log_event("security_bot", "Encryption round-trip verification passed")
        print("[security_bot] Encryption round-trip verification passed", file=sys.stderr)
    except Exception as e:
        log_event("security_bot", f"Encryption verification failed: {e}", level="error")
        print(f"[security_bot] Encryption verification failed: {e}", file=sys.stderr)
        raise

def decrypt_env_bot():
    """
    Decrypts the .env_bot.enc file and prints the contents to stdout (NEVER writes to disk here).
    """
    key = load_encryption_key()
    fernet = Fernet(key)
    if not ENC_BOT_ENV_PATH.exists():
        raise FileNotFoundError(f"{ENC_BOT_ENV_PATH} not found")
    encrypted_data = ENC_BOT_ENV_PATH.read_bytes()
    try:
        decrypted_data = fernet.decrypt(encrypted_data)
        print(decrypted_data.decode())
        print("[security_bot] Decrypted .env_bot.enc successfully", file=sys.stderr)
    except InvalidToken:
        log_event("security_bot", "Invalid decryption token—likely wrong key.", level="error")
        print("[security_bot] Invalid decryption token—likely wrong key.", file=sys.stderr)
        raise

def write_decrypted_env_to_file():
    """
    Decrypts .env_bot.enc and writes contents back to .env_bot (for bootstrap/dev only; destructive overwrite).
    """
    key = load_encryption_key()
    fernet = Fernet(key)
    if not ENC_BOT_ENV_PATH.exists():
        raise FileNotFoundError(f"{ENC_BOT_ENV_PATH} not found")
    encrypted_data = ENC_BOT_ENV_PATH.read_bytes()
    try:
        decrypted_data = fernet.decrypt(encrypted_data)
        _backup_file(BOT_ENV_PATH, "env_bot_plain")
        BOT_ENV_PATH.write_bytes(decrypted_data)
        log_event("security_bot", "Decrypted .env_bot.enc to .env_bot (overwrote existing)")
        print("[security_bot] Decrypted .env_bot.enc to .env_bot (overwrote existing)", file=sys.stderr)
    except InvalidToken:
        log_event("security_bot", "Invalid decryption token—likely wrong key.", level="error")
        print("[security_bot] Invalid decryption token—likely wrong key.", file=sys.stderr)
        raise

def secure_write_encrypted_category(category: str, data_dict: dict):
    """
    Securely writes a dict of key/values for the given category to encrypted storage using Fernet.
    Category should be a string (e.g., 'broker', 'smtp', 'bot_identity', etc).
    """
    support_dir = Path(__file__).resolve().parent.parent / "support"
    category_map = {
        "bot_identity": support_dir / ".bot_identity.enc",
        "broker": support_dir / ".broker.enc",
        "smtp": support_dir / ".smtp.enc",
        "network_config": support_dir / ".network_config.enc",
        "screener_api": support_dir / ".screener_api.enc",
        "acct_api": support_dir / ".acct_api.enc",
    }
    enc_file = category_map.get(category)
    if not enc_file:
        raise ValueError(f"Unknown config category: {category}")

    key = load_encryption_key()
    fernet = Fernet(key)
    # Compose .env-style key=value content
    lines = [f"{k}={v}" for k, v in data_dict.items() if v is not None]
    content = "\n".join(lines).encode("utf-8")
    encrypted = fernet.encrypt(content)
    # Backup previous (if exists)
    if enc_file.exists():
        _backup_file(enc_file, f"{category}_enc")
    enc_file.write_bytes(encrypted)
    log_event("security_bot", f"Encrypted config for category '{category}' to {enc_file}")
    print(f"[security_bot] Encrypted config for category '{category}' to {enc_file}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tbot_bot/config/security_bot.py [encrypt|decrypt|write|rotate]")
        sys.exit(1)

    action = sys.argv[1].lower()
    if action == "encrypt":
        encrypt_env_bot()
    elif action == "decrypt":
        decrypt_env_bot()
    elif action == "write":
        write_decrypted_env_to_file()
    elif action == "rotate":
        encrypt_env_bot(rotate_key=True)
    else:
        print("Unknown action. Use encrypt, decrypt, write, or rotate.")
        sys.exit(1)
