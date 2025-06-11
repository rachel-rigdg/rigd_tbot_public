# tbot_bot/config/provisioning_runner.py
# Central orchestrator: watches for provisioning flag; calls key_manager.py, provisioning_helper.py, bootstrapping_helper.py, db_bootstrap.py; handles all setup steps and privilege/escalation

import time
import json
import subprocess
from pathlib import Path
import sys
import traceback
import os
from cryptography.fernet import Fernet

if "RIGD_TBOT_ROOT" in os.environ:
    ROOT = Path(os.environ["RIGD_TBOT_ROOT"]).resolve()
else:
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SUPPORT_PATH = ROOT / "tbot_bot" / "support"
CONFIG_PATH = ROOT / "tbot_bot" / "config"
OUTPUT_BASE = ROOT / "tbot_bot" / "output"
BOOTSTRAP_LOGS_PATH = OUTPUT_BASE / "bootstrap" / "logs"
RUNTIME_CONFIG_KEY_PATH = ROOT / "tbot_bot" / "storage" / "keys" / "runtime_config.key"
RUNTIME_CONFIG_PATH = ROOT / "tbot_bot" / "storage" / "secrets" / "runtime_config.json.enc"
PROVISION_FLAG_PATH = CONFIG_PATH / "PROVISION_FLAG"
CONTROL_DIR = ROOT / "tbot_bot" / "control"
CONTROL_START_PATH = CONTROL_DIR / "control_start.txt"
STATUS_PATH_TEMPLATE = OUTPUT_BASE / "{bot_identity}" / "logs" / "provisioning_status.json"
STATUS_BOOTSTRAP_PATH = BOOTSTRAP_LOGS_PATH / "provisioning_status.json"
BOT_STATE_FILE = CONTROL_DIR / "bot_state.txt"

sys.path.insert(0, str(CONFIG_PATH))
from tbot_bot.config.key_manager import main as key_manager_main
from tbot_bot.config.provisioning_helper import main as provisioning_helper_main
from tbot_bot.config.bootstrapping_helper import main as bootstrapping_helper_main
from tbot_bot.config.db_bootstrap import initialize_all as db_bootstrap_main

# === Added for user creation ===
from tbot_web.support.auth_web import upsert_user

def write_status(status_file, state, detail=""):
    status = {
        "status": state,
        "detail": detail,
        "utc_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file, "w") as f:
        json.dump(status, f, indent=2)

def load_runtime_config():
    if RUNTIME_CONFIG_KEY_PATH.exists() and RUNTIME_CONFIG_PATH.exists():
        try:
            key = RUNTIME_CONFIG_KEY_PATH.read_bytes()
            fernet = Fernet(key)
            enc_bytes = RUNTIME_CONFIG_PATH.read_bytes()
            config_json = fernet.decrypt(enc_bytes).decode("utf-8")
            return json.loads(config_json)
        except Exception as e:
            print(f"[provisioning_runner] ERROR loading runtime config: {e}")
    return {}

def get_bot_identity_string():
    config = load_runtime_config()
    try:
        return config["bot_identity"]["BOT_IDENTITY_STRING"]
    except Exception:
        return None

def clear_provision_flag():
    try:
        PROVISION_FLAG_PATH.unlink()
    except Exception:
        pass

def create_control_start_flag():
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    CONTROL_START_PATH.touch(exist_ok=True)
    print(f"[provisioning_runner] Created control start flag: {CONTROL_START_PATH}")

def set_bot_state(state):
    BOT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state)

def create_admin_user_from_config():
    # Load user credentials from runtime config
    config = load_runtime_config()
    try:
        admin_user = config.get("admin_user", {})
        username = admin_user.get("username", "admin")
        password = admin_user.get("userpassword", "changeme")
        email = admin_user.get("email", "admin@localhost")
        if username and password:
            upsert_user(username, password, email)
            print(f"[provisioning_runner] Created or updated admin user: {username}")
    except Exception as e:
        print(f"[provisioning_runner] Failed to create admin user: {e}")

def main():
    print("[provisioning_runner] Runner started; monitoring provisioning flag.")
    already_provisioned = False
    while True:
        if PROVISION_FLAG_PATH.exists() and not already_provisioned:
            bot_identity = get_bot_identity_string()
            if bot_identity and bot_identity != "undefined":
                status_path = OUTPUT_BASE / bot_identity / "logs" / "provisioning_status.json"
            else:
                status_path = STATUS_BOOTSTRAP_PATH
            try:
                # Set state to provisioning
                set_bot_state("provisioning")
                write_status(status_path, "pending", "Provisioning started.")
                write_status(status_path, "running", "Key generation.")
                key_manager_main()
                write_status(status_path, "running", "Provisioning secrets and minimal config.")
                provisioning_helper_main()
                write_status(status_path, "running", "Running bootstrapping helper.")
                bootstrapping_helper_main()
                write_status(status_path, "running", "Database initialization.")
                db_bootstrap_main()
                # === CREATE ADMIN USER HERE ===
                write_status(status_path, "running", "Creating initial admin user.")
                create_admin_user_from_config()
                time.sleep(0.5)
                clear_provision_flag()
                write_status(status_path, "running", "Creating control_start.txt to launch bot via systemd.")
                create_control_start_flag()
                # Update state to idle after provisioning is complete
                set_bot_state("idle")
                write_status(status_path, "complete", "Provisioning complete, control_start.txt created for bot launch.")
                already_provisioned = True
            except Exception as e:
                tb = traceback.format_exc()
                set_bot_state("error")
                write_status(status_path, "error", f"Error: {e}\nTraceback:\n{tb}")
                clear_provision_flag()
        elif not PROVISION_FLAG_PATH.exists():
            already_provisioned = False
        time.sleep(2)

if __name__ == "__main__":
    main()
