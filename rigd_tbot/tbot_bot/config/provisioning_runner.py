# tbot_bot/config/provisioning_runner.py
# Central orchestrator: watches for provisioning flag; calls key_manager.py, provisioning_helper.py, bootstrapping_helper.py, db_bootstrap.py; handles all setup steps and privilege/escalation

import time
import json
import subprocess
from pathlib import Path
import sys
import traceback
import os

# Inject root to sys.path to fix module resolution
if "RIGD_TBOT_ROOT" in os.environ:
    ROOT = Path(os.environ["RIGD_TBOT_ROOT"]).resolve()
else:
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SUPPORT_PATH = ROOT / "tbot_bot" / "support"
CONFIG_PATH = ROOT / "tbot_bot" / "config"
OUTPUT_BASE = ROOT / "tbot_bot" / "output"
BOOTSTRAP_LOGS_PATH = OUTPUT_BASE / "bootstrap" / "logs"
TMP_CONFIG_PATH = SUPPORT_PATH / "tmp" / "bootstrap_config.json"
PROVISION_FLAG_PATH = CONFIG_PATH / "PROVISION_FLAG"
STATUS_PATH_TEMPLATE = OUTPUT_BASE / "{bot_identity}" / "logs" / "provisioning_status.json"
STATUS_BOOTSTRAP_PATH = BOOTSTRAP_LOGS_PATH / "provisioning_status.json"

# Provisioning step modules
sys.path.insert(0, str(CONFIG_PATH))
from tbot_bot.config.key_manager import main as key_manager_main
from tbot_bot.config.provisioning_helper import main as provisioning_helper_main
from tbot_bot.config.bootstrapping_helper import main as bootstrapping_helper_main
from tbot_bot.config.db_bootstrap import initialize_all as db_bootstrap_main

def write_status(status_file, state, detail=""):
    status = {
        "status": state,
        "detail": detail,
        "utc_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file, "w") as f:
        json.dump(status, f, indent=2)

def get_bot_identity_string():
    try:
        with open(TMP_CONFIG_PATH, "r") as f:
            config = json.load(f)
        return config["bot_identity"]["BOT_IDENTITY_STRING"]
    except Exception:
        return None

def clear_provision_flag():
    try:
        PROVISION_FLAG_PATH.unlink()
    except Exception:
        pass

def trigger_tbot_bot_service():
    try:
        subprocess.run(
            ['sudo', 'systemctl', 'start', 'tbot_bot.service'],
            check=True
        )
        print("[provisioning_runner] tbot_bot.service triggered via systemd.")
    except Exception as e:
        raise RuntimeError(f"Failed to start tbot_bot.service: {e}")

def main():
    print("[provisioning_runner] Runner started; monitoring provisioning flag.")
    while True:
        if PROVISION_FLAG_PATH.exists():
            bot_identity = get_bot_identity_string()
            # Write provisioning status to bootstrap/logs/ until bot_identity is available
            if bot_identity and bot_identity != "undefined":
                status_path = OUTPUT_BASE / bot_identity / "logs" / "provisioning_status.json"
            else:
                status_path = STATUS_BOOTSTRAP_PATH
            try:
                write_status(status_path, "pending", "Provisioning started.")
                write_status(status_path, "running", "Key generation.")
                key_manager_main()
                write_status(status_path, "running", "Provisioning secrets and minimal config.")
                provisioning_helper_main()
                write_status(status_path, "running", "Running bootstrapping helper.")
                bootstrapping_helper_main()
                write_status(status_path, "running", "Database initialization.")
                db_bootstrap_main()
                write_status(status_path, "running", "Triggering tbot_bot.service via systemd.")
                trigger_tbot_bot_service()
                write_status(status_path, "complete", "Provisioning complete, bot launched via systemd.")
                clear_provision_flag()
            except Exception as e:
                tb = traceback.format_exc()
                write_status(status_path, "error", f"Error: {e}\nTraceback:\n{tb}")
                clear_provision_flag()
        time.sleep(2)

if __name__ == "__main__":
    main()
