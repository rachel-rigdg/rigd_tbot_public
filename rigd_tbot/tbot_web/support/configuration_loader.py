# tbot_web/support/configuration_loader.py
# Loads and decrypts encrypted configuration files from storage/secrets/*.json.enc

import json
from pathlib import Path
from cryptography.fernet import Fernet
from tbot_bot.support.path_resolver import get_secret_path
from tbot_bot.config.config_encryption import load_key


def load_encrypted_config(category: str) -> dict:
    """
    Loads and decrypts a category config file from storage/secrets.
    Returns a dict of config key/values. Returns {} if missing or empty.
    """
    enc_path = Path(get_secret_path(category))
    if not enc_path.is_file():
        print(f"[configuration_loader] No config file found for {category}: {enc_path}")
        return {}
    try:
        key = load_key(category)
        fernet = Fernet(key)
        enc_bytes = enc_path.read_bytes()
        # Expect file as key=value pairs, one per line (not strict JSON)
        content = fernet.decrypt(enc_bytes).decode("utf-8")
        result = {}
        for line in content.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
        print(f"[configuration_loader] Loaded config for {category}: {result}")
        return result
    except Exception as e:
        print(f"[configuration_loader] ERROR loading {category}: {e}")
        return {}

def load_all_config(categories: list) -> dict:
    """
    Loads all requested config categories, returns dict {category: {k:v}}
    """
    configs = {}
    for cat in categories:
        configs[cat] = load_encrypted_config(cat)
    return configs
