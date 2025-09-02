# tbot_bot/config/provisioning_runner.py
# Central orchestrator: watches for provisioning flag; calls key_manager.py, provisioning_helper.py,
# bootstrapping_helper.py, db_bootstrap.py; handles all setup steps and privilege/escalation

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
CONTROL_START_PATH = CONTROL_DIR / "control_start.flag"
STATUS_PATH_TEMPLATE = OUTPUT_BASE / "{bot_identity}" / "logs" / "provisioning_status.json"
STATUS_BOOTSTRAP_PATH = BOOTSTRAP_LOGS_PATH / "provisioning_status.json"
BOT_STATE_FILE = CONTROL_DIR / "bot_state.txt"

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


# -----------------------------
# Minimal, targeted additions
# -----------------------------
def _apply_accounting_bootstrap_and_seed(status_path):
    """
    After DB schema/init: post opening entries (if present) and load default COA mapping seed (if requested, once).
    Reads ONLY from runtime_config.json.enc that was written by the Configuration UI.
    """
    cfg = load_runtime_config() or {}
    bot_meta = (cfg.get("bot_identity") or {})
    identity = bot_meta.get("BOT_IDENTITY_STRING") or ""
    try:
        entity, jurisdiction, broker, bot_id = identity.split("_", 3)
    except Exception:
        # If identity is not fully available, skip bootstrap (schema/init already completed).
        print("[provisioning_runner] Skipping accounting bootstrap: invalid BOT_IDENTITY_STRING.")
        return

    # ---- Opening entries (optional) ----
    ab = cfg.get("accounting_bootstrap") or cfg.get("ACCOUNTING_BOOTSTRAP") or {}
    # We accept either:
    #   - {'present': True, 'date_utc': 'YYYY-MM-DD', 'entries': [ {account_code|account, amount, memo?}, ... ]}
    #   - or flat key 'OPENING_BALANCE_ENTRIES_JSON' (JSON string) and 'OPENING_BALANCE_DATE_UTC'
    ob_present = bool(ab.get("present") or ab.get("OPENING_BALANCE_PRESENT"))
    entries = ab.get("entries") or ab.get("lines")
    date_utc = ab.get("date_utc") or ab.get("OPENING_BALANCE_DATE_UTC")

    if not entries and cfg.get("OPENING_BALANCE_ENTRIES_JSON"):
        try:
            entries = json.loads(cfg["OPENING_BALANCE_ENTRIES_JSON"])
            if isinstance(entries, dict) and "entries" in entries:
                entries = entries["entries"]
        except Exception:
            entries = None
        date_utc = date_utc or cfg.get("OPENING_BALANCE_DATE_UTC")

    # Post only if we have entries and a date
    if entries and date_utc:
        try:
            write_status(status_path, "running", "Posting opening balance entries.")
            from tbot_bot.accounting.ledger_modules.ledger_bootstrap import write_opening_entries
            actor = "bootstrap"
            # write_opening_entries validates and posts balanced double-entry group per date_utc
            write_opening_entries(entity, jurisdiction, broker, bot_id, entries, actor, date_utc=date_utc)
            print("[provisioning_runner] Opening entries posted.")
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[provisioning_runner] Opening entries failed: {e}\n{tb}")
            # Non-fatal: continue provisioning; ledger remains empty if this failed.

    # ---- COA mapping seed (optional/one-time) ----
    seed_flag = (
        cfg.get("LOAD_DEFAULT_COA_SEED")
        or (isinstance(ab, dict) and ab.get("load_default_coa_seed"))
        or False
    )
    if seed_flag:
        try:
            write_status(status_path, "running", "Loading default COA mapping seed (if empty).")
            from tbot_bot.accounting.ledger_modules.mapping_auto_update import load_default_seed_if_empty
            load_default_seed_if_empty(actor="bootstrap")
            print("[provisioning_runner] Default COA mapping seed ensured.")
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[provisioning_runner] COA mapping seed load failed: {e}\n{tb}")
            # Non-fatal: continue provisioning


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

                # >>> Surgical addition: post opening entries + optional COA seed <<<
                _apply_accounting_bootstrap_and_seed(status_path)

                time.sleep(0.5)
                clear_provision_flag()
                write_status(status_path, "running", "Creating control_start.flag to launch bot via systemd.")
                create_control_start_flag()
                set_bot_state("bootstrapping")
                write_status(status_path, "bootstrapping", "Provisioning and bootstrapping complete, initializing core databases before registration.")
                # Wait for database bootstrap completion, then registration
                time.sleep(1)
                set_bot_state("registration")
                write_status(status_path, "waiting_registration", "Bootstrapping complete, registration required before bot launch.")
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
