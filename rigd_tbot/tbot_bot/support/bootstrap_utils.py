# tbot_bot/support/bootstrap_utils.py

from pathlib import Path

KEYS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"
CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"

CONFIG_REQUIRED_FILES = [
    KEYS_DIR / "bot_identity.key",
    KEYS_DIR / "login.key",
    SECRETS_DIR / "bot_identity.json.enc",
    SECRETS_DIR / "broker_credentials.json.enc",
    SECRETS_DIR / "network_config.json.enc",
]

INITIALIZE_STATES = ("initialize", "provisioning", "bootstrapping", "registration")


def is_first_bootstrap(quiet_mode: bool = False) -> bool:
    """
    Returns True only if bot_state.txt is missing or its stripped content matches any "initialize", "provisioning", "bootstrapping", "registration".
    Prevents provisioning/redirect after initial bootstrap.
    BOOTSTRAP_FLAG is deprecated and ignored; logic is now driven by bot_state.txt.
    Debugs all checked paths and values to stdout for diagnostics unless quiet_mode is True.
    """
    def debug_print(msg):
        if not quiet_mode:
            print(msg)

    debug_print(f"[DEBUG] BOT_STATE_PATH: {BOT_STATE_PATH} (exists: {BOT_STATE_PATH.exists()})")
    if not BOT_STATE_PATH.exists():
        debug_print("[DEBUG] bot_state.txt missing")
        return True
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        state = state.splitlines()[0].strip() if state else ""
        debug_print(f"[DEBUG] bot_state.txt state: {state}")
        if state in INITIALIZE_STATES:
            debug_print(f"[DEBUG] bot_state.txt state is {state}")
            return True
    except Exception as e:
        debug_print(f"[DEBUG] Exception reading bot_state.txt: {e}")
        return True
    for file_path in CONFIG_REQUIRED_FILES:
      #  debug_print(f"[DEBUG] Checking existence: {file_path} ({file_path.exists()})")
        if not file_path.exists():
            debug_print(f"[DEBUG] Required file missing: {file_path}")
            return True
    debug_print("[DEBUG] is_first_bootstrap returning False")
    return False

def get_boot_identity_string():
    """
    Reads and returns BOT_IDENTITY_STRING from decrypted bot_identity.json.enc.
    Returns 'UNKNOWN_BOT' if missing or malformed.
    """
    try:
        from tbot_bot.support.decrypt_secrets import load_bot_identity
        bot_identity_data = load_bot_identity()
        if isinstance(bot_identity_data, dict):
            return bot_identity_data.get("BOT_IDENTITY_STRING", "UNKNOWN_BOT")
        if isinstance(bot_identity_data, str):
            return bot_identity_data
        return "UNKNOWN_BOT"
    except Exception:
        return "UNKNOWN_BOT"
