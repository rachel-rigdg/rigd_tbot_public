# tbot_bot/support/encrypt_secrets.py
# Encrypts JSON files in /storage/secrets/ using Fernet keys stored in /storage/keys/

import json
from pathlib import Path
from cryptography.fernet import Fernet
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.utils_time import utc_now

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

# Example direct usage
if __name__ == "__main__":
    try:
        from tbot_bot.support.decrypt_secrets import decrypt_json

        plaintext = decrypt_json("env")
        encrypt_json("env", plaintext)
        print(f"[encrypt_secrets] Successfully re-encrypted env.json.enc")

    except Exception as e:
        print(f"[encrypt_secrets] Error: {e}")
