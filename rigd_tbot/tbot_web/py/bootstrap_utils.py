# tbot_web/py/bootstrap_utils.py

from pathlib import Path

KEYS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"
CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
BOOTSTRAP_FLAG = CONTROL_DIR / "BOOTSTRAP_FLAG"

CONFIG_REQUIRED_FILES = [
    KEYS_DIR / "bot_identity.key",
    KEYS_DIR / "login.key",
    SECRETS_DIR / "bot_identity.json.enc",
    SECRETS_DIR / "broker_credentials.json.enc",
    SECRETS_DIR / "network_config.json.enc",
]

def is_first_bootstrap() -> bool:
    """
    Return True if BOOTSTRAP_FLAG is missing, or any required key or secret config file is missing.
    Prevent provisioning before config is saved.
    """
    if not BOOTSTRAP_FLAG.exists():
        return True
    for file_path in CONFIG_REQUIRED_FILES:
        if not file_path.exists():
            return True
    return False

def get_boot_identity_string():
    """
    Reads and returns BOT_IDENTITY_STRING from decrypted bot_identity.json.enc.
    Returns 'UNKNOWN_BOT' if missing or malformed.
    """
    try:
        from tbot_bot.support.decrypt_secrets import load_bot_identity
        bot_identity_data = load_bot_identity()
        if (
            not bot_identity_data
            or not isinstance(bot_identity_data, dict)
            or "BOT_IDENTITY_STRING" not in bot_identity_data
        ):
            return "UNKNOWN_BOT"
        return bot_identity_data["BOT_IDENTITY_STRING"]
    except Exception:
        return "UNKNOWN_BOT"
