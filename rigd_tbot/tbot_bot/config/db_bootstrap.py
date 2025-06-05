# tbot_bot/config/db_bootstrap.py
# Thin wrapper: initializes all core system databases by shelling out to core/scripts/init_*.py
# Never duplicates or maintains its own schema/init logic.

import subprocess
from pathlib import Path
from tbot_bot.support.utils_log import log_event
from cryptography.fernet import Fernet
import json

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "core" / "scripts"
ACCOUNTING_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "accounting"
KEYS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"

INIT_SCRIPTS = [
    "init_system_users.py",
    "init_system_logs.py",
    "init_user_activity_monitoring.py",
    "init_password_reset_tokens.py"
]

ACCOUNTING_INIT = [
    "init_ledger_db.py",
    "init_coa_db.py"
]

def _decrypt_bot_identity() -> dict:
    key_path = KEYS_DIR / "bot_identity.key"
    secret_path = SECRETS_DIR / "bot_identity.json.enc"
    if not key_path.exists() or not secret_path.exists():
        raise FileNotFoundError("Bot identity key or secret file missing")
    key = key_path.read_bytes()
    fernet = Fernet(key)
    encrypted_data = secret_path.read_bytes()
    decrypted = fernet.decrypt(encrypted_data)
    return json.loads(decrypted)

def initialize_all():
    """
    Calls each core DB CLI script to initialize all mandatory DBs,
    then ensures accounting output folders exist and creates ledger/COA DBs using decrypted bot_identity.
    """
    print("[db_bootstrap] Initializing core system databases via CLI scripts...")
    for script in INIT_SCRIPTS:
        script_path = SCRIPT_DIR / script
        if script_path.is_file():
            try:
                print(f"[db_bootstrap] Running: {script_path}")
                subprocess.run(["python3", str(script_path)], check=True)
                log_event("db_bootstrap", f"Successfully ran DB init script: {script_path}")
            except subprocess.CalledProcessError as e:
                log_event("db_bootstrap", f"Error running DB init script {script_path}: {e}", level="error")
                print(f"[db_bootstrap] ERROR: Failed to run {script_path}: {e}")
                raise
        else:
            log_event("db_bootstrap", f"Missing DB init script: {script_path}", level="error")
            print(f"[db_bootstrap] ERROR: Missing script: {script_path}")
            raise FileNotFoundError(f"Missing DB init script: {script_path}")
    log_event("db_bootstrap", "All core system databases initialized via CLI scripts.")
    print("[db_bootstrap] All core system databases initialized via CLI scripts.")

    # --- Ensure accounting output folders exist and build ledgers if BOT_IDENTITY is available ---
    try:
        from tbot_bot.accounting import accounting_config

        bot_identity = _decrypt_bot_identity()
        BOT_IDENTITY = bot_identity.get("BOT_IDENTITY_STRING", "")
        print(f"[db_bootstrap] Decrypted BOT_IDENTITY_STRING: {BOT_IDENTITY}")  # <--- Added print
        if BOT_IDENTITY:
            ENTITY, JURISDICTION, BROKER, BOT_ID = BOT_IDENTITY.split("_")
            accounting_config.ensure_output_folder_structure()
            for script in ACCOUNTING_INIT:
                script_path = ACCOUNTING_DIR / script
                if script_path.is_file():
                    try:
                        print(f"[db_bootstrap] Running: {script_path} for {ENTITY} {JURISDICTION} {BROKER} {BOT_ID}")
                        subprocess.run([
                            "python3", str(script_path),
                            ENTITY, JURISDICTION, BROKER, BOT_ID
                        ], check=True)
                        log_event("db_bootstrap", f"Successfully ran accounting DB init script: {script_path}")
                    except subprocess.CalledProcessError as e:
                        log_event("db_bootstrap", f"Error running accounting DB init script {script_path}: {e}", level="error")
                        print(f"[db_bootstrap] ERROR: Failed to run {script_path}: {e}")
                        raise
                else:
                    log_event("db_bootstrap", f"Missing accounting DB init script: {script_path}", level="error")
                    print(f"[db_bootstrap] ERROR: Missing script: {script_path}")
                    raise FileNotFoundError(f"Missing accounting DB init script: {script_path}")
        else:
            print("[db_bootstrap] BOT_IDENTITY_STRING missing from decrypted bot_identity secret; skipping ledger/COA creation")
    except Exception as e:
        print(f"[db_bootstrap] Skipping ledger/COA creation due to error: {e}")

# CLI direct execution (optional/no-op for production)
if __name__ == "__main__":
    initialize_all()
