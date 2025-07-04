# tbot_bot/config/key_manager.py
# Generates, loads, and validates Fernet encryption keys for all secret categories

from pathlib import Path
from cryptography.fernet import Fernet
from tbot_bot.support.utils_log import log_event
from tbot_bot.config.config_encryption import encrypt_and_write
import os
import base64
import json

KEY_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"
KEY_DIR.mkdir(parents=True, exist_ok=True)

POSTCONFIG_KEYS = [
    "bot_identity",
    "network_config",
    "alert",
    "broker",
    "smtp",
    "screener_api",
    "acct_api",
    "broker_credentials",
    "smtp_credentials",
    "acct_api_credentials",
    "alert_channels"
]

def load_secret_json(category):
    path = SECRETS_DIR / f"{category}.json"
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def generate_key_file(key_name: str, force_rotate=False, reencrypt_secret=True):
    key_path = KEY_DIR / f"{key_name}.key"
    if key_path.exists() and not force_rotate:
        log_event("key_manager", f"Key already exists, not overwriting: {key_path}")
        return
    key = Fernet.generate_key()
    if len(base64.urlsafe_b64decode(key)) != 32:
        raise ValueError(f"Invalid Fernet key generated for: {key_name}")
    key_path.write_text(key.decode("utf-8"))
    os.chmod(key_path, 0o600)
    log_event("key_manager", f"Generated new Fernet key: {key_path}")
    if reencrypt_secret and key_name in ["bot_identity", "network_config"]:
        data = load_secret_json(key_name)
        if data:
            encrypt_and_write(key_name, data)

def rotate_all_postconfig_keys():
    for key_name in POSTCONFIG_KEYS:
        generate_key_file(key_name, force_rotate=True)

def generate_all_postconfig_keys():
    for key_name in POSTCONFIG_KEYS:
        generate_key_file(key_name)

def main(rotate=False):
    if rotate:
        rotate_all_postconfig_keys()
    else:
        generate_all_postconfig_keys()
    log_event("key_manager", "All Fernet keys generated and validated.")
