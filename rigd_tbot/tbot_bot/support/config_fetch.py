# tbot_bot/support/config_fetch.py
# Fetches the current, decrypted runtime config as a dict for key/secret rotation or validation

from pathlib import Path
import json
from cryptography.fernet import Fernet

RUNTIME_CONFIG_KEY_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "runtime_config.key"
RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "runtime_config.json.enc"

def get_live_config_for_rotation():
    """
    Loads and decrypts the current runtime config from disk.
    Returns the config as a dict, or empty dict if not found or on error.
    """
    if RUNTIME_CONFIG_KEY_PATH.exists() and RUNTIME_CONFIG_PATH.exists():
        try:
            key = RUNTIME_CONFIG_KEY_PATH.read_bytes()
            fernet = Fernet(key)
            data = fernet.decrypt(RUNTIME_CONFIG_PATH.read_bytes()).decode("utf-8")
            return json.loads(data)
        except Exception:
            return {}
    return {}
