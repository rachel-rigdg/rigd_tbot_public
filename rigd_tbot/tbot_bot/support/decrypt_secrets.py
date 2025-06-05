# tbot_bot/support/decrypt_secrets.py
# Loads and decrypts .json.enc files using corresponding Fernet keys

import json
from pathlib import Path
from typing import Dict, Optional
from cryptography.fernet import Fernet
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event       

# Constants: All relative to storage/
ROOT = Path(__file__).resolve().parents[1] / "storage"
KEY_DIR = ROOT / "keys"
ENCRYPTED_DIR = ROOT / "secrets"

# Throttle for missing identity warnings (per session)
_warned_missing_identity = False

def load_key(key_name: str) -> bytes:
    """
    Loads a Fernet key from the /storage/keys/ directory.
    """
    key_path = KEY_DIR / f"{key_name}.key"
    if not key_path.is_file():
        raise FileNotFoundError(f"Missing key file: {key_path}")
    return key_path.read_text(encoding="utf-8").strip().encode()

def decrypt_json(name: str) -> Dict:
    """
    Decrypts an encrypted JSON file named {name}.json.enc using {name}.key.
    Returns the decrypted data as a Python dictionary.
    """
    key = load_key(name)
    fernet = Fernet(key)
    enc_path = ENCRYPTED_DIR / f"{name}.json.enc"
    if not enc_path.is_file():
        # DEBUG: log the path being checked for troubleshooting initial bootstrap
        log_event("decrypt_secrets", f"DEBUG: Looking for encrypted file at: {enc_path}", level="warning")
        raise FileNotFoundError(f"Missing encrypted file: {enc_path}")

    try:
        encrypted_data = enc_path.read_bytes()
        decrypted = fernet.decrypt(encrypted_data)
        parsed = json.loads(decrypted.decode("utf-8"))
        # log_event("decrypt_secrets", f"Successfully decrypted {name}.json.enc at {utc_now().isoformat()}")
        return parsed
    except Exception as e:
        log_event("decrypt_secrets", f"Failed to decrypt {name}.json.enc: {e}", level="error")
        raise RuntimeError(f"Decryption failed for {name}.json.enc: {e}")

def load_bot_identity(default: Optional[str] = None) -> Optional[str]:
    """
    Decrypts and returns the BOT_IDENTITY_STRING from bot_identity.json.enc.
    Returns default if missing or file not found, else raises if present but blank.
    Throttles warning log to fire only once per process.
    """
    global _warned_missing_identity
    try:
        data = decrypt_json("bot_identity")
        identity = data.get("BOT_IDENTITY_STRING")
        if not identity:
            if default is not None:
                return default
            raise KeyError("BOT_IDENTITY_STRING missing in bot_identity.json.enc")
        return identity
    except FileNotFoundError:
        if not _warned_missing_identity:
            log_event("decrypt_secrets", "bot_identity.json.enc or key not found; returning default", level="warning")
            _warned_missing_identity = True
        return default
    except Exception:
        # Catch all unexpected exceptions, but throttle logging to one warning
        if not _warned_missing_identity:
            log_event("decrypt_secrets", "bot_identity.json.enc or key not found; returning default", level="warning")
            _warned_missing_identity = True
        return default

# Example direct usage
if __name__ == "__main__":
    try:
        data = decrypt_json("env")  # Example: decrypt env.json.enc using env.key
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"[decrypt_secrets] {e}")