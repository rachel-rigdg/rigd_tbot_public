# tbot_bot/config/key_manager.py
# Generates, loads, and validates Fernet encryption keys for all secret categories

from pathlib import Path
from cryptography.fernet import Fernet
from tbot_bot.support.utils_log import log_event
import os
import base64

KEY_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
KEY_DIR.mkdir(parents=True, exist_ok=True)

POSTCONFIG_KEYS = [
    "bot_identity",
    "network_config",
    "alert",
    "broker",
    "login",
    "smtp",
    "screener_api",
    "acct_api",
    "broker_credentials",
    "smtp_credentials",
    "acct_api_credentials",
    "alert_channels"
]

def generate_key_file(key_name: str):
    key_path = KEY_DIR / f"{key_name}.key"
    if not key_path.exists():
        key = Fernet.generate_key()
        if len(base64.urlsafe_b64decode(key)) != 32:
            raise ValueError(f"Invalid Fernet key generated for: {key_name}")
        key_path.write_text(key.decode("utf-8"))
        os.chmod(key_path, 0o600)
        log_event("key_manager", f"Generated new Fernet key: {key_path}")
    else:
        log_event("key_manager", f"Key already exists, not overwriting: {key_path}")

def generate_all_postconfig_keys():
    for key_name in POSTCONFIG_KEYS:
        generate_key_file(key_name)

def main():
    generate_all_postconfig_keys()
    log_event("key_manager", "All Fernet keys generated and validated.")