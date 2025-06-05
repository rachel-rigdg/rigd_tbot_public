# tools/build_check.py
# Automated Build Check Utility for TradeBot v1.0.0 (RIGD_TradingBot_v040)
#
# Validates essential files, encryption keys, schemas, directories, and config integrity
# Ensures compliance with project specifications before build/deploy/run.
#
# Usage: python3 build_check.py
# Returns exit code 0 if all checks pass, non-zero otherwise.

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import re
import json
from cryptography.fernet import Fernet
from tbot_bot.support.path_resolver import get_output_path, validate_bot_identity

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = PROJECT_ROOT / "tbot_bot" / "storage"
SECRETS_DIR = STORAGE_DIR / "secrets"
KEYS_DIR = STORAGE_DIR / "keys"
SUPPORT_DIR = PROJECT_ROOT / "tbot_bot" / "support"
CORE_SCHEMAS_DIR = PROJECT_ROOT / "tbot_bot" / "core" / "schemas"

# Required key files
REQUIRED_KEYS = [
    "env.key",
    "env_bot.key",
    "login.key",
    "broker_credentials.key",
    "smtp_credentials.key",
    "screener_api.key",
    "acct_api_credentials.key",
    "alert_channels.key",
    "env.key",
    "bot_identity.key",
    "network_config.key"
]

# Required encrypted secret files
REQUIRED_SECRETS = [
    "bot_identity.json.enc",
    "broker_credentials.json.enc",
    "network_config.json.enc",
    "smtp_credentials.json.enc",
    "screener_api.json.enc",
    "acct_api_credentials.json.enc",
    "alert_channels.json.enc"
]

# Required core database files (presence and schema validation handled separately)
REQUIRED_DATABASES = [
    PROJECT_ROOT / "tbot_bot" / "core" / "databases" / "SYSTEM_USERS.db",
    PROJECT_ROOT / "tbot_bot" / "core" / "databases" / "SYSTEM_LOGS.db",
    PROJECT_ROOT / "tbot_bot" / "core" / "databases" / "USER_ACTIVITY_MONITORING.db",
    PROJECT_ROOT / "tbot_bot" / "core" / "databases" / "PASSWORD_RESET_TOKENS.db"
]

# Required schema files (core)
REQUIRED_SCHEMAS = [
    CORE_SCHEMAS_DIR / "system_users_schema.sql",
    CORE_SCHEMAS_DIR / "system_logs_schema.sql",
    CORE_SCHEMAS_DIR / "user_activity_monitoring_schema.sql",
    CORE_SCHEMAS_DIR / "password_reset_schema.sql"
]

# Required static asset directories (check presence)
REQUIRED_STATIC_DIRS = [
    PROJECT_ROOT / "tbot_web" / "static" / "css",
    PROJECT_ROOT / "tbot_web" / "static" / "fnt",
]

IDENTITY_PATTERN = r"^[A-Z]{2,6}_[A-Z]{2,4}_[A-Z]{2,10}_[0-9]{2,4}$"

def check_file_exists(path: Path) -> bool:
    if not path.is_file():
        print(f"[ERROR] Missing file: {path}")
        return False
    return True

def check_dir_exists(path: Path) -> bool:
    if not path.is_dir():
        print(f"[ERROR] Missing directory: {path}")
        return False
    return True

def check_fernet_key_valid(path: Path) -> bool:
    try:
        key_text = path.read_text(encoding="utf-8").strip()
        Fernet(key_text.encode())  # Will raise if invalid
        return True
    except Exception as e:
        print(f"[ERROR] Invalid Fernet key at {path}: {e}")
        return False

def check_json_enc_decryptable(enc_path: Path, key_path: Path) -> bool:
    try:
        from cryptography.fernet import Fernet
        enc_bytes = enc_path.read_bytes()
        key_text = key_path.read_text(encoding="utf-8").strip()
        fernet = Fernet(key_text.encode())
        decrypted_bytes = fernet.decrypt(enc_bytes)
        json.loads(decrypted_bytes.decode("utf-8"))
        return True
    except Exception as e:
        print(f"[ERROR] Failed to decrypt or parse JSON from {enc_path} with key {key_path}: {e}")
        return False

def main():
    print("=== TradeBot Build Check v040 ===")
    errors_found = False

    # Check keys
    print("\nChecking encryption keys...")
    for key_file in REQUIRED_KEYS:
        key_path = KEYS_DIR / key_file
        if not check_file_exists(key_path):
            errors_found = True
            continue
        if not check_fernet_key_valid(key_path):
            errors_found = True

    # Check encrypted secret files decryptable
    print("\nChecking encrypted secret files...")
    for secret_file in REQUIRED_SECRETS:
        enc_path = SECRETS_DIR / secret_file
        key_name = secret_file.split(".")[0]  # e.g. env.json.enc -> env
        key_path = KEYS_DIR / f"{key_name}.key"
        if not check_file_exists(enc_path):
            errors_found = True
            continue
        if not check_file_exists(key_path):
            errors_found = True
            continue
        if not check_json_enc_decryptable(enc_path, key_path):
            errors_found = True

    # Check core databases presence
    print("\nChecking core database files...")
    for db_path in REQUIRED_DATABASES:
        if not check_file_exists(db_path):
            errors_found = True

    # Check core schema files presence
    print("\nChecking core schema files...")
    for schema_path in REQUIRED_SCHEMAS:
        if not check_file_exists(schema_path):
            errors_found = True

    # Check static asset directories
    print("\nChecking static asset directories...")
    for static_dir in REQUIRED_STATIC_DIRS:
        if not check_dir_exists(static_dir):
            errors_found = True

    # Check output directories using path_resolver for all valid identity dirs
    print("\nChecking output directories...")
    output_categories = ["logs", "ledgers", "summaries", "trades"]
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    if not base_output_dir.exists():
        print(f"[WARNING] Output directory does not exist: {base_output_dir}")
    else:
        for identity_dir in base_output_dir.iterdir():
            if not identity_dir.is_dir():
                continue
            identity = identity_dir.name
            # Skip {bot_identity} and bootstrap
            if identity in ("{bot_identity}", "bootstrap"):
                continue
            if not re.match(IDENTITY_PATTERN, identity):
                continue
            try:
                validate_bot_identity(identity)
            except Exception:
                print(f"[ERROR] Invalid bot identity dir: {identity_dir}")
                errors_found = True
                continue
            for category in output_categories:
                try:
                    cat_dir = Path(get_output_path(identity, category, "", True))
                    if not cat_dir.exists():
                        print(f"[WARNING] Output subdirectory missing: {cat_dir}")
                    elif not os.access(cat_dir, os.W_OK):
                        print(f"[ERROR] Output subdirectory not writable: {cat_dir}")
                        errors_found = True
                except Exception as e:
                    print(f"[ERROR] Output path check failed for {identity}:{category} → {e}")
                    errors_found = True

    # Check COA/ledger database files for each identity output directory
    print("\nChecking COA/ledger output database files...")
    for identity_dir in base_output_dir.iterdir():
        if identity_dir.is_dir():
            identity = identity_dir.name
            # Skip {bot_identity} and bootstrap
            if identity in ("{bot_identity}", "bootstrap"):
                continue
            if "_" not in identity:
                continue
            ledgers_dir = identity_dir / "ledgers"
            coa_db = ledgers_dir / f"{identity}_BOT_COA_v1.0.0.db"
            ledger_db = ledgers_dir / f"{identity}_BOT_ledger.db"
            if not coa_db.exists():
                print(f"[ERROR] Missing COA DB: {coa_db}")
                errors_found = True
            if not ledger_db.exists():
                print(f"[ERROR] Missing ledger DB: {ledger_db}")
                errors_found = True

    print("\n=== Build check complete ===")
    if errors_found:
        print("[RESULT] Build check FAILED. Please fix the above errors.")
        sys.exit(1)
    else:
        print("[RESULT] Build check PASSED. Ready for build/deployment.")
        sys.exit(0)

if __name__ == "__main__":
    main()
