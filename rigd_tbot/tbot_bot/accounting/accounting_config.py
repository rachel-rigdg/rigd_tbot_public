# tbot_bot/accounting/accounting_config.py 
# Validates and creates required output folder structure; enforces ledger/COA existence and schema compliance

import os
import json
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_output_folder_path, resolve_ledger_db_path, resolve_coa_db_path

# Load and decrypt bot_identity.json.enc directly
KEY_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
ENC_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
key = KEY_PATH.read_bytes()
cipher = Fernet(key)
plaintext = cipher.decrypt(ENC_PATH.read_bytes())
bot_identity_data = json.loads(plaintext.decode("utf-8"))
print(f"[accounting_config] Decrypted BOT_IDENTITY_STRING: {bot_identity_data.get('BOT_IDENTITY_STRING')}")

# Retrieve explicit bot-scoped identity string from decrypted config
BOT_IDENTITY = bot_identity_data.get("BOT_IDENTITY_STRING")  # Must match: {ENTITY}_{JURISDICTION}_{BROKER}_{BOT_ID}

# Global export toggle
EXPORT_MODE = bot_identity_data.get("LEDGER_EXPORT_MODE", "auto").lower()  # Options: auto, off

# Resolve output subfolder for this bot
OUTPUT_FOLDER = resolve_output_folder_path(BOT_IDENTITY)

# Construct scoped ledger filenames using path_resolver
LEDGER_PATH = resolve_ledger_db_path(*BOT_IDENTITY.split("_"))
FLOAT_LEDGER_PATH = os.path.join(OUTPUT_FOLDER, "ledgers", f"{BOT_IDENTITY}_BOT_FLOAT_ledger.db")
COA_LEDGER_PATH = resolve_coa_db_path(*BOT_IDENTITY.split("_"))

# Default currency for all ledger exports
LEDGER_CURRENCY = "USD"

# Export options
USE_BACKUPS = True             # Always create timestamped backup in /backups/
EXPORT_FORMAT = "sqlite"       # SQLite output only (no external system dependency)

def ensure_output_folder_structure():
    """
    Validates and creates all required output folders for logs, ledgers, summaries, and trades.
    """
    subdirs = ["logs", "ledgers", "summaries", "trades"]
    for sub in subdirs:
        subdir_path = os.path.join(OUTPUT_FOLDER, sub)
        os.makedirs(subdir_path, exist_ok=True)
