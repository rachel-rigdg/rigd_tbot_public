# tbot_bot/config/provisioning_helper.py
# Generates and saves all required Fernet keys and minimal secrets once; idempotent; called only from provisioning_runner.py

from tbot_web.support.security_users import (
    generate_or_load_login_keypair,
    generate_and_save_broker_keys,
    generate_and_save_smtp_keys,
    generate_and_save_screener_keys,
    generate_and_save_acctapi_keys,
    generate_and_save_alert_keys,
    generate_and_save_network_config_keys,
    generate_and_save_bot_identity_key,
    write_encrypted_bot_identity_secret,
    write_encrypted_network_config_secret,
    write_encrypted_alert_secret,
    write_encrypted_broker_secret,
    write_encrypted_smtp_secret,
    write_encrypted_screener_api_secret,
    write_encrypted_acctapi_secret,
)
from tbot_bot.config.key_manager import main as key_manager_main
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import json

TMP_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "support" / "tmp" / "bootstrap_config.json"
RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "runtime_config.json.enc"
RUNTIME_CONFIG_KEY_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "runtime_config.key"
KEYS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"
STATE_FILE = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
KEYS_DIR.mkdir(parents=True, exist_ok=True)
SECRETS_DIR.mkdir(parents=True, exist_ok=True)

def set_bot_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state)

def load_runtime_config():
    from cryptography.fernet import Fernet
    if RUNTIME_CONFIG_PATH.exists() and RUNTIME_CONFIG_KEY_PATH.exists():
        try:
            key = RUNTIME_CONFIG_KEY_PATH.read_bytes()
            fernet = Fernet(key)
            enc_bytes = RUNTIME_CONFIG_PATH.read_bytes()
            content = fernet.decrypt(enc_bytes).decode("utf-8")
            return json.loads(content)
        except Exception as e:
            print(f"[provisioning_helper] ERROR decrypting runtime_config: {e}")
    return None

def rotate_all_keys_and_secrets(config: dict) -> None:
    """
    Generates new Fernet keys for ALL secrets, then re-encrypts ALL secrets with new keys.
    To be called after any key/secret change (such as registration).
    """
    key_manager_main()
    generate_and_save_bot_identity_key()
    generate_or_load_login_keypair()
    generate_and_save_broker_keys()
    generate_and_save_smtp_keys()
    generate_and_save_screener_keys()
    generate_and_save_acctapi_keys()
    generate_and_save_alert_keys()
    generate_and_save_network_config_keys()
    # --- PATCH: ALWAYS WRITE BOT_IDENTITY SECRET USING LATEST CONFIG ---
    write_encrypted_bot_identity_secret(config.get("bot_identity", {}))
    write_encrypted_network_config_secret(config.get("network_config", {}))
    write_encrypted_alert_secret(config.get("alert_channels", {}))
    write_encrypted_broker_secret(config.get("broker", {}))
    write_encrypted_smtp_secret(config.get("smtp", {}))
    write_encrypted_screener_api_secret(config.get("screener_api", {}))
    write_encrypted_acctapi_secret(config.get("acct_api", {}))
    log_event("provisioning", "All Fernet keys rotated and all secrets re-encrypted.")

def provision_keys_and_secrets(config: dict = None) -> None:
    """
    Loads config from runtime_config.json.enc, or TMP_CONFIG_PATH if not provided.
    Generate all Fernet keys, then generate and write all encrypted secret files independently.
    """
    print("[provisioning_helper] Starting provisioning process...")
    try:
        set_bot_state("provisioning")
        if config is None or not config:
            config = load_runtime_config()
        if config is None:
            if TMP_CONFIG_PATH.exists():
                with open(TMP_CONFIG_PATH, "r") as f:
                    config = json.load(f)
            else:
                raise FileNotFoundError("[provisioning_helper] No config found in runtime_config or TMP_CONFIG_PATH")

        bot_identity = config.get("bot_identity", {})
        if "BOT_IDENTITY_STRING" not in bot_identity or not bot_identity["BOT_IDENTITY_STRING"]:
            bot_identity["BOT_IDENTITY_STRING"] = (
                f"{bot_identity.get('ENTITY_CODE', '')}_{bot_identity.get('JURISDICTION_CODE', '')}_"
                f"{bot_identity.get('BROKER_CODE', '')}_{bot_identity.get('BOT_ID', '')}"
            )
            config["bot_identity"] = bot_identity
        print(f"[provisioning_helper] bot_identity created/set: {config['bot_identity']}")

        # --- PATCH: ENSURE BOT_IDENTITY SECRET IS ALWAYS FRESH FROM CONFIG ---
        write_encrypted_bot_identity_secret(config.get("bot_identity", {}))

        rotate_all_keys_and_secrets(config)
        print("[provisioning_helper] All keys written and all secrets re-encrypted.")

        log_event("provisioning", "Provisioning completed: keys generated and secrets written.")
        set_bot_state("bootstrapping")
        print("[provisioning_helper] Provisioning completed successfully.")
    except Exception as e:
        log_event("provisioning", f"Provisioning failed: {e}", level="error")
        set_bot_state("error")
        print(f"[provisioning_helper] Provisioning failed: {e}")
        raise

def main():
    provision_keys_and_secrets()
