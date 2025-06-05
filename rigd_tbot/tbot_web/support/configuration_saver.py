# tbot_web/support/configuration_saver.py
# saves and encrypts configuration files from storage/secrets/*.json.enc

from tbot_bot.config.config_encryption import secure_write_encrypted_category
from pathlib import Path

SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"

def save_encrypted_config(categories: dict) -> None:
    """
    Write encrypted category files for config data.
    Always use static path override for all categories to avoid dependencies on keys or bot_identity during initial save.
    """
    print("[save_encrypted_config] Starting encryption for config categories")
    for category, data in categories.items():
        if any(data.values()):
            print(f"[save_encrypted_config] Encrypting category: {category}")
            enc_path = SECRETS_DIR / f"{category}.json.enc"
            print(f"[save_encrypted_config] Using static secrets path for: {category} -> {enc_path}")
            secure_write_encrypted_category(category, data, path_override=enc_path)
    print("[save_encrypted_config] All category configs encrypted")
