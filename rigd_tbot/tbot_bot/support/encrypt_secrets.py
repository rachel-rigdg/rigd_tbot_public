# tbot_bot/support/encrypt_secrets.py
# Encrypts JSON files in /storage/secrets/ using Fernet keys stored in /storage/keys/

import json
from pathlib import Path
from cryptography.fernet import Fernet
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.utils_time import utc_now

from tbot_bot.support.config_fetch import get_live_config_for_rotation
from tbot_bot.config.provisioning_helper import rotate_all_keys_and_secrets
from tbot_bot.support.bootstrap_utils import is_first_bootstrap

# Constants
ROOT = Path(__file__).resolve().parents[1] / "storage"
KEY_DIR = ROOT / "keys"
SECRETS_DIR = ROOT / "secrets"

def load_key(key_name: str, default=None) -> bytes:
    """
    Loads a Fernet key from /storage/keys/{key_name}.key
    Returns default if missing and default is provided, else raises.
    """
    key_path = KEY_DIR / f"{key_name}.key"
    if not key_path.is_file():
        if default is not None:
            return default
        raise FileNotFoundError(f"Missing key file: {key_path}")
    return key_path.read_text(encoding="utf-8").strip().encode()

def encrypt_json(name: str, data: dict) -> None:
    """
    Encrypts the given dictionary as JSON into {name}.json.enc using {name}.key.
    Writes encrypted file to /storage/secrets/.
    """
    key = load_key(name)
    fernet = Fernet(key)
    json_bytes = json.dumps(data, indent=2).encode("utf-8")

    enc_path = SECRETS_DIR / f"{name}.json.enc"
    encrypted = fernet.encrypt(json_bytes)

    with open(enc_path, "wb") as f:
        f.write(encrypted)

    log_event("encrypt_secrets", f"Encrypted {name}.json.enc at {utc_now().isoformat()}")

def encrypt_all_secrets(secret_data_map: dict):
    """
    Rotates all secrets with new keys. Expects {name: dict} mapping.
    """
    for name, data in secret_data_map.items():
        encrypt_json(name, data)
    log_event("encrypt_secrets", f"All secrets encrypted/rotated at {utc_now().isoformat()}")

def rotate_all_keys_and_secrets_cli():
    """
    CLI entrypoint: Performs atomic rotation using the canonical config, post-bootstrap only.
    """
    if not is_first_bootstrap():
        config = get_live_config_for_rotation()
        if config:
            rotate_all_keys_and_secrets(config)
            print("[encrypt_secrets] All keys and secrets rotated successfully.")
        else:
            print("[encrypt_secrets] No config found, rotation skipped.")
    else:
        print("[encrypt_secrets] Rotation not allowed during first bootstrap.")

# Example direct usage
if __name__ == "__main__":
    try:
        rotate_all_keys_and_secrets_cli()
    except Exception as e:
        print(f"[encrypt_secrets] Error: {e}")
